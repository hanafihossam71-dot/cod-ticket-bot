import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Select, Modal, TextInput
import asyncio
import io
import datetime
import os
import time
import uuid
import re
import hashlib
import aiohttp
from aiohttp import web
from typing import Optional

# ======================== بيانات السيرفر والتصنيفات ========================
TOKEN = os.environ.get("DISCORD_TOKEN", "")

WELCOME_CHANNEL_ID = 1552627900191219752        # آيدي روم welcome
SUPPORT_ROLE_ID = 1552628903481184336            # آيدي رتبة Admin
TICKET_CATEGORY_ID = 1552642061608419408       # تصنيف تذاكر الطلبات العامة (Tickets ✅)
SELL_CATEGORY_ID = 1552642160992591892           # تصنيف تذاكر بيع الحسابات
TICKET_LOGS_CHANNEL_ID = 1552640603639259207     # روم حفظ سجلات التذاكر المحذوفة
MARKETPLACE_CHANNEL_ID = 1553436681611386961     # روم المنتدى (Forum Channel) للمعروضات
REVIEW_CHANNEL_ID = 1552643577547456564          # روم مراجعة الإدارة
VOUCH_CHANNEL_ID = 1552628000000000000           # آيدي روم الفيدباك (vouches-feedback)

WEB_PORT = int(os.environ.get("PORT", 8080))
BASE_WEB_URL = os.environ.get("BASE_WEB_URL", "https://cod-ticket-bot-production.up.railway.app")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SHOP_URL = os.environ.get("SHOP_URL", "https://projeto-optmus-prime.vercel.app").rstrip("/")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DEFAULT_SHOP_ENTRY_CHANNEL_ID = 1554581284112826429
SHOP_ENTRY_CHANNEL_ID = int(os.environ.get("SHOP_ENTRY_CHANNEL_ID", str(DEFAULT_SHOP_ENTRY_CHANNEL_ID)) or DEFAULT_SHOP_ENTRY_CHANNEL_ID)

SELLER_TICKET_CLOSE_DELAY_SECONDS = 60
SELLER_PORTAL_ACTIVE_GRACE_SECONDS = 3600
SELLER_TICKET_SCAN_INTERVAL_SECONDS = 15

CRYPTO_ADDRESSES = {
    "USDT_TRC20": "TYourTRC20AddressHereXXXXXXXXXXXXXX",
    "USDT_BEP20": "0xYourBEP20AddressHereXXXXXXXXXXXXXX",
    "LTC": "LYourLitecoinAddressHereXXXXXXXXXXXXXX",
    "BTC": "bc1qYourBitcoinAddressHereXXXXXXXXXXXXXX"
}
# ======================================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def dedupe_file_paths_by_content(paths: list[str]) -> list[str]:
    """Preserve upload order while removing byte-identical images."""
    unique_paths = []
    seen_hashes = set()
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as image_file:
            for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        if checksum in seen_hashes:
            continue
        seen_hashes.add(checksum)
        unique_paths.append(path)
    return unique_paths

async def supabase_request(method: str, endpoint: str, *, json_data=None, body=None, content_type=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Railway.")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    if json_data is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
    if content_type:
        headers["Content-Type"] = content_type
        headers["x-upsert"] = "false"
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.request(method, f"{SUPABASE_URL}{endpoint}", headers=headers, json=json_data, data=body) as response:
            text_body = await response.text()
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Supabase request failed ({response.status}): {text_body[:500]}")
            if not text_body:
                return None
            try:
                return await response.json()
            except Exception:
                return text_body

async def create_supabase_listing(listing_id: str, seller_id: int, seller_ticket_channel_id: int, title: str, price: float, currency: str, category: str | None, categories: list[str], description: str, image_paths: list):
    """Create one pending listing and its images; compensate on partial failure."""
    uploaded_objects = []
    try:
        rows = await supabase_request(
            "POST", "/rest/v1/listings",
            json_data={
                "id": listing_id,
                "seller_discord_id": str(seller_id),
                "seller_ticket_channel_id": int(seller_ticket_channel_id),
                "title": title,
                "price": price,
                "currency": currency,
                # Keep the legacy primary category for backwards compatibility,
                # but persist every selected Seller Portal highlight as well.
                "category": category,
                "categories": categories,
                "description": description,
                "status": "PENDING_REVIEW",
                "sort_order": 0,
            },
        )
        if not isinstance(rows, list) or not rows or not rows[0].get("id"):
            raise RuntimeError("Supabase did not return the new listing ID.")
        image_rows = []
        for index, image_path in enumerate(image_paths):
            if not os.path.isfile(image_path):
                raise RuntimeError("An uploaded image is missing from the server.")
            ext = os.path.splitext(image_path)[1].lower() or ".jpg"
            object_path = f"{listing_id}/{index:02d}-{uuid.uuid4().hex}{ext}"
            with open(image_path, "rb") as image_file:
                payload = image_file.read()
            mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/gif" if ext == ".gif" else "image/jpeg"
            await supabase_request("POST", f"/storage/v1/object/listing-images/{object_path}", body=payload, content_type=mime)
            uploaded_objects.append(object_path)
            image_rows.append({"listing_id": listing_id, "image_url": object_path, "sort_order": index})

        if image_rows:
            await supabase_request("POST", "/rest/v1/listing_images", json_data=image_rows)
        return listing_id
    except Exception:
        # Best-effort rollback so a failed upload does not leave a half-created offer.
        if uploaded_objects:
            try:
                await supabase_request(
                    "DELETE", "/storage/v1/object/listing-images",
                    json_data={"prefixes": uploaded_objects},
                )
            except Exception as cleanup_error:
                print(f"Supabase storage rollback error for {listing_id}: {cleanup_error}")
        # The POST may have reached Supabase even if the client timed out,
        # so attempt deletion by the stable session UUID in every failure case.
        try:
            await supabase_request("DELETE", f"/rest/v1/listings?id=eq.{listing_id}")
        except Exception as cleanup_error:
            print(f"Supabase listing rollback error for {listing_id}: {cleanup_error}")
        raise

async def set_listing_status(listing_id: str, status: str):
    if not listing_id:
        return

    update_data = {"status": status}
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if status == "PUBLISHED":
        update_data["published_at"] = now_iso
    elif status == "SOLD":
        update_data["sold_at"] = now_iso

    rows = await supabase_request(
        "PATCH", f"/rest/v1/listings?id=eq.{listing_id}",
        json_data=update_data,
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("No matching listing was updated in Supabase.")

async def fetch_listing_by_offer_number(offer_number: int, *, published_only: bool = False):
    status_filter = "&status=eq.PUBLISHED" if published_only else ""
    rows = await supabase_request(
        "GET",
        f"/rest/v1/listings?offer_number=eq.{offer_number}{status_filter}&select=id,offer_number,title,price,currency,status&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None

async def fetch_listing_by_id(listing_id: str, *, published_only: bool = False):
    status_filter = "&status=eq.PUBLISHED" if published_only else ""
    rows = await supabase_request(
        "GET",
        f"/rest/v1/listings?id=eq.{listing_id}{status_filter}&select=id,offer_number,title,price,currency,status&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None

async def get_active_purchase_ticket(buyer_id: int):
    rows = await supabase_request(
        "GET",
        f"/rest/v1/purchase_tickets?buyer_discord_id=eq.{buyer_id}&status=eq.ACTIVE&select=id,buyer_discord_id,channel_id,guild_id,status&limit=1",
    )
    return rows[0] if isinstance(rows, list) and rows else None

async def register_purchase_ticket(buyer_id: int, channel: discord.TextChannel):
    rows = await supabase_request(
        "POST", "/rest/v1/purchase_tickets",
        json_data={
            "buyer_discord_id": str(buyer_id),
            "channel_id": str(channel.id),
            "guild_id": str(channel.guild.id),
            "status": "ACTIVE",
        },
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Could not persist the purchase ticket.")
    return rows[0]

async def close_persisted_purchase_ticket(channel_id: int):
    try:
        await supabase_request(
            "PATCH",
            f"/rest/v1/purchase_tickets?channel_id=eq.{channel_id}&status=eq.ACTIVE",
            json_data={"status": "CLOSED", "closed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        )
    except Exception as e:
        print(f"Purchase ticket persistence close error for {channel_id}: {e}")

async def get_ticket_offer(ticket_id: int, listing_id: str):
    rows = await supabase_request(
        "GET",
        f"/rest/v1/purchase_ticket_offers?ticket_id=eq.{ticket_id}&listing_id=eq.{listing_id}&select=id,ticket_id,listing_id,offer_number,status,sold_notified_at&limit=1",
    )
    return rows[0] if isinstance(rows, list) and rows else None

async def add_ticket_offer(ticket_id: int, listing: dict):
    rows = await supabase_request(
        "POST", "/rest/v1/purchase_ticket_offers",
        json_data={
            "ticket_id": ticket_id,
            "listing_id": str(listing["id"]),
            "offer_number": int(listing["offer_number"]),
            "status": "ACTIVE",
        },
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Could not persist the offer in the purchase ticket.")
    return rows[0]

async def remove_ticket_offer(ticket_id: int, listing_id: str):
    await supabase_request("DELETE", f"/rest/v1/purchase_ticket_offers?ticket_id=eq.{ticket_id}&listing_id=eq.{listing_id}")

async def get_ticket_offers(ticket_id: int, *, active_only: bool = False):
    status_filter = "&status=eq.ACTIVE" if active_only else ""
    rows = await supabase_request(
        "GET",
        f"/rest/v1/purchase_ticket_offers?ticket_id=eq.{ticket_id}{status_filter}&select=id,ticket_id,listing_id,offer_number,status,sold_notified_at&order=created_at.asc",
    )
    return rows if isinstance(rows, list) else []

async def get_active_ticket_by_channel(channel_id: int):
    rows = await supabase_request(
        "GET",
        f"/rest/v1/purchase_tickets?channel_id=eq.{channel_id}&status=eq.ACTIVE&select=id,buyer_discord_id,channel_id,guild_id,status&limit=1",
    )
    return rows[0] if isinstance(rows, list) and rows else None

async def get_interested_active_tickets(listing_id: str):
    links = await supabase_request(
        "GET",
        f"/rest/v1/purchase_ticket_offers?listing_id=eq.{listing_id}&select=id,ticket_id,listing_id,offer_number,status,sold_notified_at",
    )
    if not isinstance(links, list):
        return []
    result = []
    for link in links:
        ticket_rows = await supabase_request(
            "GET",
            f"/rest/v1/purchase_tickets?id=eq.{link['ticket_id']}&status=eq.ACTIVE&select=id,buyer_discord_id,channel_id,guild_id,status&limit=1",
        )
        if isinstance(ticket_rows, list) and ticket_rows:
            result.append((ticket_rows[0], link))
    return result

async def mark_ticket_offer_sold(link_id: int, *, notified: bool = False):
    data = {"status": "SOLD"}
    if notified:
        data["sold_notified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await supabase_request("PATCH", f"/rest/v1/purchase_ticket_offers?id=eq.{link_id}", json_data=data)

def normalize_offer_number(value: str | int | None) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None

def format_offer_id(offer_number: int) -> str:
    return f"{int(offer_number):02d}#"

def format_listing_price(listing: dict) -> str:
    currency = listing.get("currency", "USD")
    symbol = "$" if currency == "USD" else "€" if currency == "EUR" else ""
    try:
        number = float(listing.get("price", 0))
        amount = f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"
    except Exception:
        amount = str(listing.get("price", ""))
    return f"{symbol}{amount} {currency}".strip()

def _format_status_highlights(categories) -> str:
    if not categories:
        return "None"
    if isinstance(categories, str):
        raw = [categories]
    else:
        raw = list(categories)
    labels = {
        "TOP_250": "Top 250",
        "NUKES": "Nukes",
        "IRIDESCENT": "Iridescent",
    }
    values = [labels.get(str(item).upper(), str(item).replace("_", " ").title()) for item in raw if str(item).strip()]
    return " • ".join(values) if values else "None"


def build_seller_status_embed(
    *,
    status: str,
    seller_mention: str,
    offer_id: str,
    offer_title: str,
    price_str: str,
    highlights: str,
    screenshots: str,
    reason: str | None = None,
    avatar_url: str | None = None,
) -> discord.Embed:
    """Build the single canonical seller-facing status card for one listing."""
    status = str(status or "").upper()
    if status == "PUBLISHED":
        title = f"✅ {offer_id} — APPROVED & PUBLISHED"
        intro = f"Great news {seller_mention}! Your Call of Duty account listing has been approved and is now live in the Accounts Shop."
        current_status = "Published / Live"
        color = 0x10B981
        footer = "Pedrao22k Services • Listing Live"
        extra = "\n\n🛒 **OPEN ACCOUNTS SHOP:** Use the button below to view the live offer inside Discord."
    elif status == "REJECTED":
        title = f"❌ {offer_id} — LISTING DECLINED BY STAFF"
        intro = f"Hello {seller_mention}, your submitted Call of Duty account listing has been inspected and **declined** by moderation."
        current_status = "Rejected / Action Required"
        color = 0xEF4444
        footer = "Pedrao22k Services • Moderation Decision"
        extra = (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "### 📝 REASON FOR REJECTION:\n"
            f"> ⚠️ **`{reason or 'No reason provided.'}`**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛠️ **WHAT YOU CAN DO:**\n"
            "• Please re-read our safety rules (strictly no gamer tags, nicknames, or watermarks).\n"
            "• The **Seller Portal** remains available in this ticket so you can submit a corrected offer."
        )
    elif status == "SOLD":
        title = f"⛔ {offer_id} — SOLD / NO LONGER AVAILABLE"
        intro = f"{seller_mention}, this Call of Duty account listing has been marked as **sold** and is no longer available in the Accounts Shop."
        current_status = "Sold / No Longer Available"
        color = 0x6B7280
        footer = "Pedrao22k Services • Listing Sold"
        extra = ""
    else:
        title = f"🚀 {offer_id} — OFFER SUBMITTED TO STAFF"
        intro = f"Thank you {seller_mention}! Your Call of Duty account listing has been securely recorded."
        current_status = "Pending Admin Verification"
        color = 0xF59E0B
        footer = "Pedrao22k Services • Awaiting Review"
        extra = ""

    embed = discord.Embed(
        title=title,
        description=(
            f"{intro}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "### 📋 SUBMISSION OVERVIEW:\n"
            f"> 🆔 **Offer:** `{offer_id}`\n"
            f"> 🏷️ **Offer Title:** `{offer_title}`\n"
            f"> 💰 **Asking Price:** `{price_str}`\n"
            f"> 🌟 **Highlights:** `{highlights or 'None'}`\n"
            f"> 📸 **Screenshots Verified:** `{screenshots}`\n"
            f"> {'✅' if status == 'PUBLISHED' else '❌' if status == 'REJECTED' else '⛔' if status == 'SOLD' else '⏳'} **Current Status:** `{current_status}`"
            f"{extra}"
        ),
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text=footer)
    return embed


async def persist_seller_status_message_id(listing_id: str, message_id: int):
    """Best-effort persistence used so /sold can edit the same seller card later."""
    if not listing_id or not message_id:
        return
    try:
        await supabase_request(
            "PATCH",
            f"/rest/v1/listings?id=eq.{listing_id}",
            json_data={"seller_status_message_id": int(message_id)},
        )
    except Exception as e:
        # Keep listing workflows working even if an older database has not received the V5.62 column yet.
        print(f"Seller status message persistence warning for {listing_id}: {e}")


async def fetch_listing_status_context(offer_number: int):
    """Fetch data needed to update the seller status card; gracefully supports pre-V5.62 schema."""
    select_new = "id,offer_number,title,price,currency,status,seller_discord_id,seller_ticket_channel_id,seller_status_message_id,categories"
    try:
        rows = await supabase_request(
            "GET",
            f"/rest/v1/listings?offer_number=eq.{int(offer_number)}&select={select_new}&limit=1",
        )
    except Exception as e:
        print(f"V5.62 listing context fallback for {offer_number}: {e}")
        rows = await supabase_request(
            "GET",
            f"/rest/v1/listings?offer_number=eq.{int(offer_number)}&select=id,offer_number,title,price,currency,status,seller_discord_id,seller_ticket_channel_id,categories&limit=1",
        )
    return rows[0] if isinstance(rows, list) and rows else None


async def fetch_listing_image_count(listing_id: str) -> int:
    try:
        rows = await supabase_request(
            "GET",
            f"/rest/v1/listing_images?listing_id=eq.{listing_id}&select=id",
        )
        return len(rows) if isinstance(rows, list) else 0
    except Exception as e:
        print(f"Listing image count warning for {listing_id}: {e}")
        return 0


async def locate_seller_status_message(guild: discord.Guild | None, listing: dict) -> discord.Message | None:
    """Resolve the canonical seller card by persisted ID, with a safe legacy scan fallback."""
    if not guild or not listing:
        return None
    channel_id = listing.get("seller_ticket_channel_id")
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return None

    message_id = listing.get("seller_status_message_id")
    if message_id:
        try:
            return await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # Legacy fallback for listings created before V5.62. Only touch bot-authored
    # messages whose embed title contains the exact offer ID.
    offer_id = format_offer_id(int(listing.get("offer_number") or 0))
    try:
        async for msg in channel.history(limit=100):
            if msg.author.id != guild.me.id or not msg.embeds:
                continue
            title = msg.embeds[0].title or ""
            if offer_id in title and any(marker in title for marker in ("OFFER SUBMITTED", "APPROVED", "DECLINED", "SOLD")):
                await persist_seller_status_message_id(str(listing["id"]), msg.id)
                return msg
    except Exception as e:
        print(f"Legacy seller status message scan warning for {offer_id}: {e}")
    return None


async def update_seller_status_card_for_sold(guild: discord.Guild | None, offer_number: int):
    """Best-effort SOLD transition for the seller's canonical listing card."""
    try:
        listing = await fetch_listing_status_context(offer_number)
        if not listing:
            return
        message = await locate_seller_status_message(guild, listing)
        if not message:
            return
        seller_id = listing.get("seller_discord_id")
        seller_mention = f"<@{seller_id}>" if seller_id else "Seller"
        count = await fetch_listing_image_count(str(listing["id"]))
        screenshots = f"{count} proofs uploaded" if count else "Uploaded proofs"
        embed = build_seller_status_embed(
            status="SOLD",
            seller_mention=seller_mention,
            offer_id=format_offer_id(int(listing["offer_number"])),
            offer_title=str(listing.get("title") or "Untitled Offer"),
            price_str=format_listing_price(listing),
            highlights=_format_status_highlights(listing.get("categories")),
            screenshots=screenshots,
        )
        await message.edit(embed=embed, view=None)
    except Exception as e:
        # SOLD must never fail just because the historical seller card cannot be edited.
        print(f"Seller SOLD status card update warning for {offer_number}: {e}")


def purchase_ticket_topic(listing_id: str, offer_number: int, buyer_id: int) -> str:
    return f"pedrao22k_purchase;listing_id={listing_id};offer_number={offer_number};buyer_id={buyer_id}"

def seller_listing_topic(listing_id: str, offer_number: int, seller_id: int) -> str:
    # Lets an Activity launched from the seller ticket resolve the exact approved offer
    # without using a public website link.
    return f"pedrao22k_seller_listing;listing_id={listing_id};offer_number={offer_number};seller_id={seller_id}"


def seller_ticket_topic(seller_id: int, *, close_at: int = 0, hold_open: bool = False) -> str:
    """Persistent seller-room state. Kept in the Discord topic so restarts do not lose auto-close state."""
    return (
        f"pedrao22k_seller_ticket;seller_id={int(seller_id)};"
        f"close_at={int(close_at or 0)};hold={1 if hold_open else 0}"
    )

def parse_seller_ticket_topic(topic: Optional[str]) -> Optional[dict]:
    result = _parse_topic_fields(topic, "pedrao22k_seller_ticket;")
    if not result or not result.get("seller_id"):
        return None
    try:
        result["seller_id"] = int(result["seller_id"])
        result["close_at"] = int(result.get("close_at") or 0)
        result["hold_open"] = str(result.get("hold", "0")) == "1"
    except (TypeError, ValueError):
        return None
    return result

def _parse_topic_fields(topic: Optional[str], prefix: str) -> Optional[dict]:
    if not topic or not topic.startswith(prefix):
        return None
    result = {}
    for piece in topic.split(";")[1:]:
        if "=" in piece:
            key, value = piece.split("=", 1)
            result[key] = value
    return result

def parse_purchase_ticket_topic(topic: Optional[str]) -> Optional[dict]:
    result = _parse_topic_fields(topic, "pedrao22k_purchase;")
    if not result or not result.get("listing_id") or not result.get("offer_number") or not result.get("buyer_id"):
        return None
    try:
        result["offer_number"] = int(result["offer_number"])
        result["buyer_id"] = int(result["buyer_id"])
    except ValueError:
        return None
    return result

def parse_seller_listing_topic(topic: Optional[str]) -> Optional[dict]:
    result = _parse_topic_fields(topic, "pedrao22k_seller_listing;")
    if not result or not result.get("listing_id") or not result.get("offer_number") or not result.get("seller_id"):
        return None
    try:
        result["offer_number"] = int(result["offer_number"])
        result["seller_id"] = int(result["seller_id"])
    except ValueError:
        return None
    return result

def parse_activity_offer_topic(topic: Optional[str]) -> Optional[dict]:
    # Purchase tickets and approved seller tickets can both launch the Activity
    # directly into their exact offer.
    return parse_purchase_ticket_topic(topic) or parse_seller_listing_topic(topic)



# Global anti-double-click guard for Discord component/modal actions that create
# messages, tickets, confirmations, publications, or other side effects.
# Navigation buttons (Prev/Next) are intentionally excluded so normal browsing
# remains responsive.
INTERACTION_CLICK_GUARD_SECONDS = 6.0
_interaction_click_guard: dict[tuple[int, int, str], float] = {}


async def allow_single_interaction(
    interaction: discord.Interaction,
    action_key: str,
    *,
    cooldown: float = INTERACTION_CLICK_GUARD_SECONDS,
    acknowledge_duplicate: bool = True,
) -> bool:
    """Return True only for the first click in a short window.

    Rapid duplicate clicks are silently acknowledged so Discord does not show
    "This interaction failed" and no duplicate message/action is created.
    """
    now = time.monotonic()
    user_id = int(getattr(interaction.user, "id", 0) or 0)
    channel_id = int(getattr(interaction, "channel_id", 0) or 0)
    key = (user_id, channel_id, action_key)

    if len(_interaction_click_guard) > 4000:
        cutoff = now - 120.0
        for old_key, old_time in list(_interaction_click_guard.items()):
            if old_time < cutoff:
                _interaction_click_guard.pop(old_key, None)

    previous = _interaction_click_guard.get(key, 0.0)
    if now - previous < cooldown:
        if acknowledge_duplicate and not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception as e:
                print(f"Duplicate interaction ACK error ({action_key}): {e}")
        return False

    _interaction_click_guard[key] = now
    return True

# Prevent duplicate Activity launch interactions from rapid/repeated clicks.
# Discord requires each component interaction to be acknowledged quickly; repeated
# LAUNCH_ACTIVITY callbacks while the same Activity is already opening can be
# rejected by the client/API and surface as "This interaction failed".
ACTIVITY_CLICK_COOLDOWN_SECONDS = 5.0
_activity_click_guard: dict[tuple[int, str], float] = {}


async def launch_activity_safely(interaction: discord.Interaction, action_key: str) -> bool:
    """Launch the Discord Activity once and silently ACK rapid duplicate clicks."""
    now = time.monotonic()
    user_id = int(interaction.user.id)
    key = (user_id, action_key)

    # Keep this small in long-running processes.
    if len(_activity_click_guard) > 2000:
        cutoff = now - 60.0
        for old_key, old_time in list(_activity_click_guard.items()):
            if old_time < cutoff:
                _activity_click_guard.pop(old_key, None)

    previous = _activity_click_guard.get(key, 0.0)
    if now - previous < ACTIVITY_CLICK_COOLDOWN_SECONDS:
        # Acknowledge the extra click without attempting to launch a second
        # Activity instance. For component interactions this produces no visible
        # "thinking" message and avoids Discord's red interaction-failed banner.
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception as e:
            print(f"Duplicate Activity click ACK error ({action_key}): {e}")
        return False

    _activity_click_guard[key] = now

    try:
        await interaction.response.launch_activity()
        return True
    except Exception as e:
        print(f"Activity launch error ({action_key}): {e}")

        # If Discord rejected the launch before the interaction was acknowledged,
        # send a normal ephemeral response so the user does not receive the generic
        # red "interaction failed" state.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    "⚠️ The Accounts Shop is already opening or Discord temporarily rejected the request. "
                    "Wait a few seconds and click once.",
                    ephemeral=True,
                )
            except Exception as ack_error:
                print(f"Activity launch failure ACK error ({action_key}): {ack_error}")
        return False


class ShopLaunchView(View):
    """Persistent button used in the public accounts-for-sale text channel."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="OPEN ACCOUNTS SHOP",
        style=discord.ButtonStyle.primary,
        custom_id="pedrao22k_open_accounts_shop_activity",
    )
    async def open_shop(self, interaction: discord.Interaction, button: Button):
        await launch_activity_safely(interaction, "shop_entry")


class PurchaseOfferActivityView(View):
    """Persistent View Offer button for purchase tickets.

    The offer is resolved from the ticket channel topic by the Activity, so the
    same persistent custom_id works for every ticket and survives bot restarts.
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="View Offer",
        style=discord.ButtonStyle.secondary,
        emoji="👁️",
        custom_id="pedrao22k_view_offer_activity",
    )
    async def view_offer(self, interaction: discord.Interaction, button: Button):
        channel_id = getattr(interaction.channel, "id", 0)
        # A unified purchase ticket can contain several offers. Resolve the
        # exact offer from the message whose View Offer button was clicked and
        # update only the Activity context stored in the channel topic.
        try:
            if isinstance(interaction.channel, discord.TextChannel) and interaction.message and interaction.message.embeds:
                offer_number = normalize_offer_number(interaction.message.embeds[0].title or "")
                if offer_number is not None:
                    listing = await fetch_listing_by_offer_number(offer_number)
                    ticket = await get_active_ticket_by_channel(interaction.channel.id)
                    if listing and ticket:
                        await interaction.channel.edit(
                            topic=purchase_ticket_topic(str(listing["id"]), offer_number, int(ticket["buyer_discord_id"])),
                            reason=f"Activity View Offer context -> {format_offer_id(offer_number)}",
                        )
        except Exception as e:
            print(f"View Offer context update error for {channel_id}: {e}")
        await launch_activity_safely(interaction, f"view_offer:{channel_id}")


class SellerApprovedActivityView(View):
    """Persistent launcher shown after a seller listing is approved.

    Unlike a normal URL button, this uses Discord's Activity launcher so the
    Accounts Shop stays inside Discord. The seller ticket topic maps the current
    channel to the exact approved offer.
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="OPEN IN ACCOUNTS SHOP",
        style=discord.ButtonStyle.primary,
        emoji="🛒",
        custom_id="pedrao22k_open_approved_seller_offer_activity",
    )
    async def open_offer(self, interaction: discord.Interaction, button: Button):
        channel_id = getattr(interaction.channel, "id", 0)
        await launch_activity_safely(interaction, f"seller_approved_offer:{channel_id}")


def find_shop_entry_channel() -> Optional[discord.TextChannel]:
    """Find the new text channel used as the Accounts Shop entry point.

    SHOP_ENTRY_CHANNEL_ID can be set later for a strict ID-based configuration.
    Until then, fall back to a normal text channel whose name contains
    'accounts-for-sale' while excluding legacy/old channels.
    """
    if SHOP_ENTRY_CHANNEL_ID:
        channel = bot.get_channel(SHOP_ENTRY_CHANNEL_ID)
        return channel if isinstance(channel, discord.TextChannel) else None

    candidates = []
    for guild in bot.guilds:
        for channel in guild.text_channels:
            name = channel.name.lower()
            if "accounts-for-sale" in name and "old" not in name:
                candidates.append(channel)
    return candidates[0] if candidates else None


def _message_has_shop_launch_button(message: discord.Message) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == "pedrao22k_open_accounts_shop_activity":
                return True
    return False


async def ensure_shop_entry_read_only(channel: discord.TextChannel):
    """Make the Shop launcher channel read-only for @everyone without replacing other overrides."""
    try:
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        overwrite.create_public_threads = False
        overwrite.create_private_threads = False
        overwrite.send_messages_in_threads = False
        await channel.set_permissions(
            channel.guild.default_role,
            overwrite=overwrite,
            reason="Pedrao22k Accounts Shop launcher channel: read-only for members",
        )
        print(f"✅ Accounts Shop channel set to read-only for @everyone: #{channel.name} ({channel.id}).")
    except Exception as e:
        # Do not block the launcher if the bot lacks Manage Channels; log the exact issue instead.
        print(f"Accounts Shop read-only permission error for #{channel.name} ({channel.id}): {e}")


async def ensure_shop_entry_message():
    """Keep the Shop entry channel to exactly one launcher message and no conversation history."""
    channel = find_shop_entry_channel()
    if channel is None:
        print("Accounts Shop entry channel not found. Set SHOP_ENTRY_CHANNEL_ID or create a text channel containing 'accounts-for-sale'.")
        return

    await ensure_shop_entry_read_only(channel)

    launcher_to_keep = None
    messages_to_delete = []
    try:
        # Scan the full channel so old conversation does not remain visible below the Activity.
        # History is newest-first, so the first launcher found is the one we preserve.
        async for message in channel.history(limit=None):
            is_launcher = False
            if bot.user and message.author.id == bot.user.id:
                is_legacy_launcher = False
                if message.embeds:
                    footer = message.embeds[0].footer.text if message.embeds[0].footer else None
                    is_legacy_launcher = footer == "Pedrao22k Accounts Shop • Live Inventory"
                is_launcher = is_legacy_launcher or _message_has_shop_launch_button(message)

            if is_launcher and launcher_to_keep is None:
                launcher_to_keep = message
            else:
                messages_to_delete.append(message)
    except Exception as e:
        print(f"Accounts Shop entry history scan error: {e}")

    try:
        if launcher_to_keep is None:
            launcher_to_keep = await channel.send(view=ShopLaunchView())
        else:
            await launcher_to_keep.edit(content=None, embeds=[], view=ShopLaunchView())

        deleted = 0
        for old_message in messages_to_delete:
            try:
                await old_message.delete()
                deleted += 1
            except discord.NotFound:
                pass
            except Exception as delete_error:
                print(f"Accounts Shop channel cleanup error ({old_message.id}): {delete_error}")

        print(
            f"✅ Accounts Shop channel locked and cleaned in #{channel.name} ({channel.id}). "
            f"Removed {deleted} old message(s); only OPEN ACCOUNTS SHOP remains."
        )
    except Exception as e:
        print(f"Accounts Shop entry message error: {e}")


async def ensure_purchase_ticket_activity_button(channel: discord.TextChannel):
    """Upgrade an existing purchase ticket's legacy URL button in place."""
    try:
        async for message in channel.history(limit=50):
            if message.author.id != bot.user.id or not message.embeds:
                continue
            footer = message.embeds[0].footer.text if message.embeds[0].footer else None
            if footer == "Pedrao22k Accounts Shop":
                await message.edit(view=PurchaseOfferActivityView())
                return True
    except Exception as e:
        print(f"Purchase ticket View Offer refresh error for {channel.id}: {e}")
    return False


async def refresh_purchase_ticket_activity_buttons():
    category = bot.get_channel(TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return
    for channel in list(category.text_channels):
        if parse_purchase_ticket_topic(channel.topic):
            await ensure_purchase_ticket_activity_button(channel)

def is_staff_member(member: discord.Member) -> bool:
    return bool(member.guild_permissions.administrator or any(role.id == SUPPORT_ROLE_ID for role in member.roles))

async def archive_and_delete_ticket(channel: discord.TextChannel, closed_by, *, reason: str, delay: int = 5):
    await close_persisted_purchase_ticket(channel.id)
    log_text = "=== PEDRAO22K. TICKET TRANSCRIPT ===\n"
    log_text += f"Ticket Name: {channel.name}\n"
    log_text += f"Closed by: {closed_by} ({getattr(closed_by, 'id', 'system')})\n"
    log_text += f"Reason: {reason}\n"
    log_text += f"Closed At: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    log_text += "====================================\n\n"

    try:
        async for message in channel.history(limit=500, oldest_first=True):
            timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
            content = message.clean_content
            if message.attachments:
                content += " [Attachments: " + ", ".join(a.url for a in message.attachments) + "]"
            log_text += f"[{timestamp}] {message.author}: {content}\n"
    except Exception as e:
        log_text += f"[Transcript read error: {e}]\n"

    logs_channel = channel.guild.get_channel(TICKET_LOGS_CHANNEL_ID)
    if logs_channel:
        try:
            transcript_file = discord.File(io.BytesIO(log_text.encode("utf-8")), filename=f"transcript-{channel.name}.txt")
            log_embed = discord.Embed(
                title="📑 TICKET CLOSED & ARCHIVED",
                description=f"Ticket **#{channel.name}** was archived.",
                color=0xEF4444,
                timestamp=datetime.datetime.utcnow(),
            )
            mention = getattr(closed_by, "mention", str(closed_by))
            log_embed.add_field(name="Closed By", value=mention, inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=True)
            log_embed.add_field(name="Channel ID", value=f"`{channel.id}`", inline=False)
            log_embed.set_footer(text="Pedrao22k Audit Logs")
            await logs_channel.send(embed=log_embed, file=transcript_file)
        except Exception as e:
            print(f"Ticket transcript log error for {channel.id}: {e}")

    if delay:
        await asyncio.sleep(delay)
    try:
        await channel.delete(reason=reason)
    except Exception as e:
        print(f"Ticket delete error for {channel.id}: {e}")

purchase_ticket_lock = asyncio.Lock()

os.makedirs("uploaded_screenshots", exist_ok=True)
active_web_sessions = {}

def build_seller_portal_welcome_embed(seller) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ CALL OF DUTY | SELLER VERIFICATION PORTAL",
        description=(
            f"Welcome {seller.mention}!\n\n"
            "### 🌐 ALL-IN-ONE SELLER DASHBOARD:\n"
            "Click the button below to open our web interface:\n"
            "> 1️⃣ Fill in your **Offer Title**, **Asking Price**, and **Description**.\n"
            "> 2️⃣ Select your account highlights (Top 250, Nukes, Iridescent).\n"
            "> 3️⃣ Upload Cover Image and Gallery Screenshots.\n"
            "> 4️⃣ Click **Submit** — your listing will be dispatched directly to Staff!\n\n"
            "♻️ **You can submit multiple accounts from this same seller room.**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 **Chat is locked:** Submissions are processed exclusively through the web portal."
        ),
        color=0xF59E0B,
    )
    return embed

def register_seller_portal_session(seller_id: int, channel_id: int, launcher_msg: discord.Message, *, session_id: Optional[str] = None) -> str:
    session_id = session_id or str(uuid.uuid4())[:8]
    active_web_sessions[session_id] = {
        "seller_id": int(seller_id),
        "channel_id": int(channel_id),
        "launcher_msg": launcher_msg,
        "created_at": datetime.datetime.utcnow(),
        "cover_file": None,
        "secondary_files": [],
        "finalize_lock": asyncio.Lock(),
        "listing_id": None,
        "all_paths": None,
        "discord_cdn_urls": [],
        "discord_uploaded_paths": [],
        "review_dispatched": False,
        "finalized": False,
    }
    return session_id

async def set_seller_ticket_state(channel: discord.TextChannel, seller_id: int, *, close_at: int = 0, hold_open: bool = False, reason: str = "Seller ticket state update"):
    await channel.edit(
        topic=seller_ticket_topic(seller_id, close_at=close_at, hold_open=hold_open),
        reason=reason,
    )

async def seller_ticket_has_pending(channel_id: int) -> bool:
    rows = await supabase_request(
        "GET",
        f"/rest/v1/listings?seller_ticket_channel_id=eq.{int(channel_id)}&status=eq.PENDING_REVIEW&select=id&limit=1",
    )
    return bool(isinstance(rows, list) and rows)

async def backfill_legacy_pending_seller_listings(seller_id: int, channel_id: int):
    """Attach pre-V5.60 pending listings to the seller room being adopted.

    Before V5.60 the listings table did not store the seller ticket channel.
    Historically there was only one active seller room per seller, so attaching
    only unresolved PENDING_REVIEW rows is the safest migration and prevents
    an old pending submission from being ignored by auto-close checks.
    """
    rows = await supabase_request(
        "GET",
        f"/rest/v1/listings?seller_discord_id=eq.{int(seller_id)}&seller_ticket_channel_id=is.null&status=eq.PENDING_REVIEW&select=id",
    )
    if not isinstance(rows, list) or not rows:
        return 0
    await supabase_request(
        "PATCH",
        f"/rest/v1/listings?seller_discord_id=eq.{int(seller_id)}&seller_ticket_channel_id=is.null&status=eq.PENDING_REVIEW",
        json_data={"seller_ticket_channel_id": int(channel_id)},
    )
    return len(rows)

async def find_or_adopt_seller_ticket(guild: discord.Guild, sell_category: discord.CategoryChannel, seller: discord.Member) -> Optional[discord.TextChannel]:
    # First use durable topic metadata across the whole guild. Staff may move a
    # ticket to another category; that must not create a duplicate seller room.
    for channel in guild.text_channels:
        meta = parse_seller_ticket_topic(channel.topic)
        if meta and int(meta.get("seller_id", 0)) == int(seller.id):
            return channel

    # Backward compatibility for seller rooms created before V5.60.
    clean_user_name = seller.name.lower().replace(" ", "-")
    legacy_name = f"🏷️・sell-{clean_user_name}"
    legacy = discord.utils.get(sell_category.text_channels, name=legacy_name)
    if not legacy:
        return None

    await set_seller_ticket_state(
        legacy, int(seller.id), close_at=0, hold_open=False,
        reason="Adopt legacy seller room into V5.60 multi-listing flow",
    )
    try:
        migrated = await backfill_legacy_pending_seller_listings(int(seller.id), legacy.id)
        if migrated:
            print(f"Adopted seller room {legacy.id}: linked {migrated} legacy pending listing(s).")
    except Exception as e:
        print(f"Legacy seller pending-listing backfill error for {legacy.id}: {e}")
    return legacy

async def mark_seller_ticket_rejection_hold(channel: discord.TextChannel, seller_id: int):
    await set_seller_ticket_state(
        channel, seller_id, close_at=0, hold_open=True,
        reason="Keep seller ticket open after rejected listing",
    )

async def mark_seller_ticket_submission_active(channel: discord.TextChannel, seller_id: int):
    # A fresh submission means the seller acted on any previous rejection and the
    # ticket must remain open while staff review is pending.
    await set_seller_ticket_state(
        channel, seller_id, close_at=0, hold_open=False,
        reason="Seller submitted another listing",
    )

async def schedule_seller_ticket_close_if_idle(channel: discord.TextChannel, seller_id: int) -> bool:
    meta = parse_seller_ticket_topic(channel.topic)
    if meta and meta.get("hold_open"):
        return False
    if await seller_ticket_has_pending(channel.id):
        if meta and meta.get("close_at"):
            await set_seller_ticket_state(channel, seller_id, close_at=0, hold_open=False, reason="Pending listing keeps seller ticket open")
        return False
    close_at = int(time.time()) + SELLER_TICKET_CLOSE_DELAY_SECONDS
    if meta and meta.get("close_at") and int(meta["close_at"]) > int(time.time()):
        return True
    await set_seller_ticket_state(
        channel, seller_id, close_at=close_at, hold_open=False,
        reason="All seller listings resolved; schedule automatic close",
    )
    try:
        await channel.send(
            "✅ **All current submissions have finished review.** This seller ticket will close automatically in **1 minute**. "
            "Open the **Seller Portal** before then if you want to submit another account."
        )
    except Exception:
        pass
    return True

async def rotate_seller_portal_session(channel: discord.TextChannel, seller, launcher_msg: discord.Message) -> discord.Message:
    session_id = str(uuid.uuid4())[:8]
    view = DirectPortalLauncherView(session_id=session_id)
    try:
        await launcher_msg.edit(embed=build_seller_portal_welcome_embed(seller), view=view)
    except Exception:
        support_role = channel.guild.get_role(SUPPORT_ROLE_ID)
        role_ping = support_role.mention if support_role else ""
        launcher_msg = await channel.send(
            content=f"{seller.mention} {role_ping}",
            embed=build_seller_portal_welcome_embed(seller),
            view=view,
        )
    register_seller_portal_session(seller.id, channel.id, launcher_msg, session_id=session_id)
    return launcher_msg

async def ensure_seller_portal_launcher(channel: discord.TextChannel, seller_id: int):
    seller = channel.guild.get_member(int(seller_id))
    if seller is None:
        try:
            seller = await channel.guild.fetch_member(int(seller_id))
        except Exception:
            return
    launcher_msg = None
    try:
        async for message in channel.history(limit=75):
            if message.author.id != bot.user.id or not message.embeds:
                continue
            if message.embeds[0].title == "⚡ CALL OF DUTY | SELLER VERIFICATION PORTAL":
                launcher_msg = message
                break
    except Exception as e:
        print(f"Seller portal launcher lookup error for {channel.id}: {e}")
    if launcher_msg is None:
        support_role = channel.guild.get_role(SUPPORT_ROLE_ID)
        role_ping = support_role.mention if support_role else ""
        launcher_msg = await channel.send(
            content=f"{seller.mention} {role_ping}",
            embed=build_seller_portal_welcome_embed(seller),
        )
    await rotate_seller_portal_session(channel, seller, launcher_msg)

def infer_legacy_seller_id_from_channel(channel: discord.TextChannel) -> Optional[int]:
    """Infer the seller from legacy private-room permission overwrites.

    A seller room historically grants View Channel directly to exactly one
    non-bot member; the Admin is a role overwrite, not a member overwrite.
    Ambiguous rooms are intentionally skipped instead of guessing.
    """
    candidates = []
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and not target.bot and overwrite.view_channel is True:
            candidates.append(int(target.id))
    return candidates[0] if len(candidates) == 1 else None

async def link_listing_to_seller_ticket(listing_id: str, channel_id: int):
    if not listing_id:
        return
    await supabase_request(
        "PATCH", f"/rest/v1/listings?id=eq.{listing_id}",
        json_data={"seller_ticket_channel_id": int(channel_id)},
    )

async def seller_ticket_has_any_listing(channel_id: int) -> bool:
    rows = await supabase_request(
        "GET",
        f"/rest/v1/listings?seller_ticket_channel_id=eq.{int(channel_id)}&select=id&limit=1",
    )
    return bool(isinstance(rows, list) and rows)

async def refresh_seller_portal_launchers():
    for guild in bot.guilds:
        sell_category = guild.get_channel(SELL_CATEGORY_ID)
        candidate_channels = list(guild.text_channels)
        for channel in candidate_channels:
            meta = parse_seller_ticket_topic(channel.topic)

            # Migrate an approved V5.57/V5.58 seller room whose topic points to
            # a single published listing. Multi-listing can no longer use that
            # single-offer topic, so preserve the relation in Supabase instead.
            if not meta:
                old_listing_meta = parse_seller_listing_topic(channel.topic)
                if old_listing_meta:
                    try:
                        seller_id = int(old_listing_meta["seller_id"])
                        await link_listing_to_seller_ticket(str(old_listing_meta["listing_id"]), channel.id)
                        await set_seller_ticket_state(
                            channel, seller_id, close_at=0, hold_open=False,
                            reason="Migrate legacy approved seller room to V5.60",
                        )
                        meta = parse_seller_ticket_topic(channel.topic)
                    except Exception as e:
                        print(f"Legacy approved seller-room migration error for {channel.id}: {e}")

            # Migrate an older seller room with no structured topic. Only inspect
            # channels in the seller category and only adopt when ownership is
            # unambiguous from Discord permission overwrites.
            if not meta and isinstance(sell_category, discord.CategoryChannel) and channel.category_id == sell_category.id:
                seller_id = infer_legacy_seller_id_from_channel(channel)
                if seller_id:
                    try:
                        await set_seller_ticket_state(
                            channel, seller_id, close_at=0, hold_open=False,
                            reason="Migrate legacy seller room to V5.60",
                        )
                        await backfill_legacy_pending_seller_listings(seller_id, channel.id)
                        meta = parse_seller_ticket_topic(channel.topic)
                    except Exception as e:
                        print(f"Legacy seller-room migration error for {channel.id}: {e}")

            if not meta:
                continue
            try:
                seller_id = int(meta["seller_id"])
                await ensure_seller_portal_launcher(channel, seller_id)
                # Recover the rare case where Railway restarted after the last
                # review finished but before the 60-second deadline was stored.
                if (not meta.get("hold_open") and not meta.get("close_at")
                        and await seller_ticket_has_any_listing(channel.id)
                        and not await seller_ticket_has_pending(channel.id)):
                    await schedule_seller_ticket_close_if_idle(channel, seller_id)
            except Exception as e:
                print(f"Seller portal restart recovery error for {channel.id}: {e}")

async def seller_ticket_autoclose_task():
    while True:
        await asyncio.sleep(SELLER_TICKET_SCAN_INTERVAL_SECONDS)
        now = int(time.time())
        for guild in list(bot.guilds):
            for channel in list(guild.text_channels):
                meta = parse_seller_ticket_topic(channel.topic)
                if not meta or not meta.get("close_at") or int(meta["close_at"]) > now:
                    continue
                try:
                    if meta.get("hold_open") or await seller_ticket_has_pending(channel.id):
                        await set_seller_ticket_state(
                            channel, int(meta["seller_id"]), close_at=0, hold_open=bool(meta.get("hold_open")),
                            reason="Automatic close cancelled after final safety check",
                        )
                        continue
                    # Clear the deadline first so the scanner cannot start a second close.
                    await set_seller_ticket_state(
                        channel, int(meta["seller_id"]), close_at=0, hold_open=False,
                        reason="Automatic seller ticket close started",
                    )
                    await archive_and_delete_ticket(
                        channel, bot.user, reason="Seller listings completed; automatic close after 1 minute", delay=0
                    )
                except Exception as e:
                    print(f"Seller ticket auto-close error for {channel.id}: {e}")

def build_welcome_embed(member: discord.Member, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ WELCOME TO PEDRAO22K.",
        description=(
            f"Hey {member.mention}, welcome to **Pedrao22k Services**!\n"
            "The premier destination for competitive boosting, accounts & mastery camos.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "### 🧭 QUICK START GUIDE:\n"
            "> 1️⃣ **Get Verified:** Unlock access in your server verification room.\n"
            "> 2️⃣ **Read Guidelines:** Make sure to check our trading policy & rules.\n"
            "> 3️⃣ **Explore Shop:** Browse our boosting, camo, and stock channels.\n"
            "> 4️⃣ **Place Order:** Ready? Open a private ticket in <#1552641905806811136>.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ **Accepted Payments:** `USDT (TRC20 / BEP20)` • `LTC` • `BTC`\n"
            "⚡ **Support:** Our verified team is available 24/7 to assist you."
        ),
        color=0xF59E0B,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if guild.icon:
        embed.set_author(name=f"{guild.name} Official", icon_url=guild.icon.url)
    embed.set_footer(text=f"Pedrao22k. | Member #{guild.member_count}")
    return embed

@bot.event
async def on_member_join(member: discord.Member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = build_welcome_embed(member, member.guild)
        await channel.send(content=f"👋 Welcome to the server, {member.mention}!", embed=embed)

@bot.event
async def on_message(message: discord.Message):
    # Keep the public Accounts Shop entry channel permanently clean.
    # Normal members are blocked by channel permissions; this also removes
    # messages from admins/other bots that can bypass those overwrites.
    if getattr(message.channel, "id", None) == SHOP_ENTRY_CHANNEL_ID:
        if not bot.user or message.author.id != bot.user.id:
            try:
                await message.delete()
            except Exception as e:
                print(f"Accounts Shop live cleanup error for message {message.id}: {e}")
        return

    if message.author.bot:
        return
    if message.channel.name.startswith("🏷️・sell-"):
        author_clean = message.author.name.lower().replace(" ", "-")
        if message.channel.name.endswith(author_clean) or not message.author.guild_permissions.administrator:
            try:
                await message.delete()
                return
            except:
                pass
    await bot.process_commands(message)

class ConfirmCloseView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Confirm Close", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_close(self, interaction: discord.Interaction, button: Button):
        channel_id = int(getattr(interaction, "channel_id", 0) or 0)
        if not await allow_single_interaction(interaction, f"confirm_close:{channel_id}", cooldown=60.0):
            return
        seller_meta = parse_seller_ticket_topic(getattr(interaction.channel, "topic", None)) if isinstance(interaction.channel, discord.TextChannel) else None
        if seller_meta:
            try:
                if await seller_ticket_has_pending(interaction.channel.id):
                    return await interaction.response.edit_message(
                        content="⚠️ **This seller ticket cannot be closed while an offer is waiting for staff review.**",
                        embed=None,
                        view=None,
                    )
            except Exception as e:
                print(f"Seller pending-close safety check error: {e}")
                return await interaction.response.edit_message(
                    content="⚠️ I could not verify the pending offers safely. Please try again in a moment.",
                    embed=None,
                    view=None,
                )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="⏳ **Archiving transcript and deleting channel in 5 seconds...**",
            embed=None,
            view=self,
        )
        await archive_and_delete_ticket(interaction.channel, interaction.user, reason="Manual ticket closure", delay=5)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_close(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, "cancel_close", cooldown=3.0):
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Ticket closure cancelled.", embed=None, view=self)

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket_prompt(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, "close_ticket_prompt", cooldown=8.0):
            return
        embed = discord.Embed(
            title="⚠️ Close Ticket Confirmation",
            description="Are you sure you want to close this ticket?\nA full transcript will be automatically saved to staff logs.",
            color=0xF59E0B
        )
        # Keep the confirmation private so repeated/abandoned confirmations never
        # clutter the ticket for everyone.
        await interaction.response.send_message(embed=embed, view=ConfirmCloseView(), ephemeral=True)

class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ranked Boosting", description="Warzone & MP Ranked Play carries/piloting", emoji="🏆", value="ranked"),
            discord.SelectOption(label="Camo Unlocks", description="Mastery camos, military challenges & leveling", emoji="🎨", value="camo"),
            discord.SelectOption(label="Buy An Account", description="Purchase a verified gaming account from our stock", emoji="🛒", value="buy-acc"),
            discord.SelectOption(label="General Support", description="Questions, partnerships, or payment assistance", emoji="💬", value="support"),
        ]
        super().__init__(placeholder="⚡ Select a service to open your ticket...", min_values=1, max_values=1, options=options, custom_id="ticket_category_select")

    async def callback(self, interaction: discord.Interaction):
        if not await allow_single_interaction(interaction, "ticket_category_select", cooldown=12.0):
            return
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        selected_service = self.values[0].capitalize()

        clean_user_name = interaction.user.name.lower().replace(" ", "-")
        channel_name = f"🎫・{self.values[0]}-{clean_user_name}"

        existing = discord.utils.get(category.text_channels, name=channel_name)
        if existing:
            return await interaction.response.send_message(f"⚠️ You already have an open ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)

        ticket_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        embed = discord.Embed(
            title="⚡ PEDRAO22K. | ORDER & SUPPORT",
            description=(
                f"Welcome {interaction.user.mention} to your private order channel!\n\n"
                f"📌 **Department:** `{selected_service}`\n"
                "💳 **Accepted Payments:** `Crypto Only` (Type `!pay` for wallet details)\n\n"
                "**Instructions:**\n"
                "• Please specify your order details (Current rank / Desired tier / Budget).\n"
                "• Our support staff will respond shortly to assist you."
            ),
            color=0xF59E0B
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Pedrao22k. | Private & Secure Order System • Click 🔒 below to close")

        role_ping = support_role.mention if support_role else ""
        await ticket_channel.send(content=f"{interaction.user.mention} {role_ping}", embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ Your ticket has been created: {ticket_channel.mention}", ephemeral=True)

class TicketLauncherView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

class RejectReasonModal(Modal, title="Listing Rejection Reason"):
    def __init__(self, seller: discord.User, ticket_channel: discord.TextChannel, launcher_msg: discord.Message = None, offer_title: str = "", price_str: str = "", items_list: str = "None", count_str: str = "", listing_id: str = "", review_message: discord.Message = None, approval_view: View = None):
        super().__init__()
        self.seller = seller
        self.ticket_channel = ticket_channel
        self.launcher_msg = launcher_msg
        self.offer_title = offer_title
        self.price_str = price_str
        self.items_list = items_list
        self.count_str = count_str
        self.listing_id = listing_id
        self.review_message = review_message
        self.approval_view = approval_view
        self.reason_input = TextInput(
            label="Reason for Declining",
            style=discord.TextStyle.paragraph,
            placeholder="e.g. Nicknames visible in screenshots, inaccurate pricing, or blurry images.",
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await allow_single_interaction(interaction, f"reject_submit:{self.listing_id}", cooldown=30.0):
            return
        reason = self.reason_input.value.strip()
        try:
            await set_listing_status(self.listing_id, "REJECTED")
        except Exception as e:
            return await interaction.response.send_message(f"❌ Could not update listing status in Supabase: `{e}`", ephemeral=True)
        if self.approval_view and self.review_message:
            try:
                for item in self.approval_view.children:
                    item.disabled = True
                await self.review_message.edit(content="❌ **Listing was rejected by staff.**", view=self.approval_view)
            except Exception as e:
                print(f"Error disabling review controls after rejection: {e}")

        await interaction.response.send_message(f"✅ Rejection reason sent to seller: `{reason}`", ephemeral=True)

        if self.launcher_msg:
            try:
                offer_number = None
                current_listing = await fetch_listing_by_id(self.listing_id)
                if current_listing and current_listing.get("offer_number") is not None:
                    offer_number = int(current_listing["offer_number"])
                rejected_embed = build_seller_status_embed(
                    status="REJECTED",
                    seller_mention=self.seller.mention,
                    offer_id=(format_offer_id(offer_number) if offer_number is not None else "Offer"),
                    offer_title=self.offer_title,
                    price_str=self.price_str,
                    highlights=self.items_list,
                    screenshots=self.count_str,
                    reason=reason,
                    avatar_url=(self.seller.display_avatar.url if self.seller.display_avatar else None),
                )
                await self.launcher_msg.edit(embed=rejected_embed, view=None)
                await persist_seller_status_message_id(self.listing_id, self.launcher_msg.id)
            except Exception as e:
                print(f"Error editing seller status card to rejected: {e}")

        try:
            await mark_seller_ticket_rejection_hold(self.ticket_channel, int(self.seller.id))
        except Exception as e:
            print(f"Seller ticket rejection hold error: {e}")
        # No second seller message here. The canonical red status card already
        # contains the decision, reason, and recovery instructions.

class MarketplaceCarouselView(View):
    def __init__(self, images: list, embed_data: discord.Embed, is_sold: bool = False):
        super().__init__(timeout=None)
        self.images = images
        self.embed_data = embed_data
        self.current_index = 0
        self.is_sold = is_sold
        self.update_buttons()

    def update_buttons(self):
        if len(self.images) <= 1:
            self.prev_btn.disabled = True
            self.next_btn.disabled = True
            self.count_btn.label = "1 / 1"
        else:
            self.prev_btn.disabled = (self.current_index == 0)
            self.next_btn.disabled = (self.current_index == len(self.images) - 1)
            self.count_btn.label = f"{self.current_index + 1} / {len(self.images)}"

        if self.is_sold:
            self.buy_btn.label = "🔒 SOLD OUT"
            self.buy_btn.style = discord.ButtonStyle.secondary
            self.buy_btn.disabled = True

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, custom_id="market_prev_btn", row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        if self.current_index > 0:
            self.current_index -= 1
            self.embed_data.set_image(url=self.images[self.current_index])
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed_data, view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.primary, disabled=True, custom_id="market_count_btn", row=0)
    async def count_btn(self, interaction: discord.Interaction, button: Button):
        pass

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, custom_id="market_next_btn", row=0)
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.embed_data.set_image(url=self.images[self.current_index])
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed_data, view=self)

    @discord.ui.button(label="Buy This Account", style=discord.ButtonStyle.success, emoji="⚡", custom_id="buy_account_direct_btn", row=1)
    async def buy_btn(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, "legacy_buy_account", cooldown=12.0):
            return
        if self.is_sold:
            return await interaction.response.send_message("❌ This account has already been sold.", ephemeral=True)

        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)
        support_role = guild.get_role(SUPPORT_ROLE_ID)

        clean_user_name = interaction.user.name.lower().replace(" ", "-")
        channel_name = f"🛒・buy-acc-{clean_user_name}"

        existing = discord.utils.get(category.text_channels, name=channel_name)
        if existing:
            return await interaction.response.send_message(f"⚠️ You already have an open buying ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)

        buy_ticket_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        price_field = next((f.value for f in self.embed_data.fields if "Asking Price" in f.name), "Check listing")

        buy_embed = discord.Embed(
            title="🛒 ACCOUNT PURCHASE ORDER",
            description=(
                f"Welcome {interaction.user.mention}!\n"
                "You opened this ticket to purchase this verified Call of Duty account:\n\n"
                f"💰 **Price:** {price_field}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💳 **Payment Methods:** `Crypto Only` (USDT / LTC / BTC)\n"
                "⚡ Type `!pay` to view our official payment addresses.\n"
                "🛡️ An admin will join shortly to facilitate the safe escrow transfer."
            ),
            color=0xF59E0B,
            timestamp=datetime.datetime.utcnow()
        )
        if self.images:
            buy_embed.set_thumbnail(url=self.images[0])
        buy_embed.set_footer(text="Pedrao22k Escrow • Fast & Secure Delivery")

        role_ping = support_role.mention if support_role else ""
        await buy_ticket_channel.send(content=f"{interaction.user.mention} {role_ping}", embed=buy_embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ Purchase ticket created! Proceed here: {buy_ticket_channel.mention}", ephemeral=True)

class AdminApprovalView(View):
    def __init__(self, seller: discord.User, embed_data: discord.Embed, ticket_channel: discord.TextChannel, images: list, launcher_msg: discord.Message = None, offer_title: str = "", price_num: str = "", currency: str = "USD", items_list: str = "None", description: str = "", count_str: str = "", listing_id: str = ""):
        super().__init__(timeout=None)
        self.seller = seller
        self.embed_data = embed_data
        self.ticket_channel = ticket_channel
        self.images = images
        self.launcher_msg = launcher_msg
        self.offer_title = offer_title
        self.price_num = price_num
        self.currency = currency
        self.items_list = items_list
        self.description = description
        self.count_str = count_str
        self.listing_id = listing_id
        self.current_index = 0
        self.posted_market_message = None
        self.created_thread = None
        self.update_carousel()

    def update_carousel(self):
        if len(self.images) <= 1:
            self.prev_img.disabled = True
            self.next_img.disabled = True
            self.counter_btn.label = "1 / 1"
        else:
            self.prev_img.disabled = (self.current_index == 0)
            self.next_img.disabled = (self.current_index == len(self.images) - 1)
            self.counter_btn.label = f"📸 {self.current_index + 1} / {len(self.images)}"

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_img(self, interaction: discord.Interaction, button: Button):
        if self.current_index > 0:
            self.current_index -= 1
            self.embed_data.set_image(url=self.images[self.current_index])
            self.update_carousel()
            await interaction.response.edit_message(embed=self.embed_data, view=self)

    @discord.ui.button(label="📸 1 / 1", style=discord.ButtonStyle.primary, disabled=True, row=0)
    async def counter_btn(self, interaction: discord.Interaction, button: Button):
        pass

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_img(self, interaction: discord.Interaction, button: Button):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.embed_data.set_image(url=self.images[self.current_index])
            self.update_carousel()
            await interaction.response.edit_message(embed=self.embed_data, view=self)

    @discord.ui.button(label="Approve & Publish to Shop", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def approve(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, f"approve_listing:{self.listing_id}", cooldown=30.0):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await set_listing_status(self.listing_id, "PUBLISHED")
            published_listing = await fetch_listing_by_id(self.listing_id, published_only=True)
            if not published_listing or published_listing.get("offer_number") is None:
                raise RuntimeError("Published listing was not returned with an offer number.")
            offer_number = int(published_listing["offer_number"])

            button.disabled = True
            self.reject.disabled = True
            await interaction.message.edit(content="✅ **Listing approved and published to Accounts Shop!**", view=self)
            await interaction.followup.send(
                f"✅ {format_offer_id(offer_number)} is now live in the Accounts Shop.",
                ephemeral=True,
            )
            if self.launcher_msg:
                try:
                    approved_embed = build_seller_status_embed(
                        status="PUBLISHED",
                        seller_mention=self.seller.mention,
                        offer_id=format_offer_id(offer_number),
                        offer_title=self.offer_title,
                        price_str=f"{self.price_num} {self.currency}",
                        highlights=self.items_list,
                        screenshots=self.count_str,
                        avatar_url=(self.seller.display_avatar.url if self.seller.display_avatar else None),
                    )
                    await self.launcher_msg.edit(embed=approved_embed, view=ShopLaunchView())
                    await persist_seller_status_message_id(self.listing_id, self.launcher_msg.id)
                except Exception as e:
                    print(f"Error editing seller status card to approved: {e}")
            # Editing a Discord message does not create a new notification. Keep one
            # concise seller ping for approval, without repeating the full listing data.
            try:
                await self.ticket_channel.send(
                    f"✅ {self.seller.mention} **{format_offer_id(offer_number)} approved and published in the Accounts Shop.**"
                )
            except Exception:
                pass
            try:
                await schedule_seller_ticket_close_if_idle(self.ticket_channel, int(self.seller.id))
            except Exception as e:
                print(f"Seller ticket close scheduling error: {e}")
        except Exception as e:
            print(f"Approval error: {e}")
            await interaction.followup.send(f"❌ Could not publish listing: `{e}`", ephemeral=True)

    @discord.ui.button(label="Reject Listing", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, f"reject_listing:{self.listing_id}", cooldown=8.0):
            return
        modal = RejectReasonModal(
            seller=self.seller,
            ticket_channel=self.ticket_channel,
            launcher_msg=self.launcher_msg,
            offer_title=self.offer_title,
            price_str=f"{self.price_num} {self.currency}",
            items_list=self.items_list,
            count_str=self.count_str,
            listing_id=self.listing_id,
            review_message=interaction.message,
            approval_view=self
        )
        await interaction.response.send_modal(modal)


class SoldConfirmationView(View):
    def __init__(self, requester_id: int, listing: dict, source_channel_id: Optional[int]):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.listing = listing
        self.source_channel_id = source_channel_id

    @discord.ui.button(label="Confirm Sold", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_sold(self, interaction: discord.Interaction, button: Button):
        offer_number_guard = int(self.listing.get("offer_number", 0) or 0)
        if not await allow_single_interaction(interaction, f"confirm_sold:{offer_number_guard}", cooldown=60.0):
            return
        if interaction.user.id != self.requester_id or not isinstance(interaction.user, discord.Member) or not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You are not allowed to confirm this action.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        listing_id = self.listing["id"]
        offer_number = int(self.listing["offer_number"])
        try:
            current = await fetch_listing_by_offer_number(offer_number)
            if not current:
                return await interaction.followup.send(f"❌ Account {format_offer_id(offer_number)} was not found.", ephemeral=True)
            if current.get("status") == "SOLD":
                return await interaction.followup.send(f"⚠️ Account {format_offer_id(offer_number)} is already marked as sold.", ephemeral=True)
            await set_listing_status(listing_id, "SOLD")
            await update_seller_status_card_for_sold(interaction.guild, offer_number)
        except Exception as e:
            return await interaction.followup.send(f"❌ Could not mark {format_offer_id(offer_number)} as sold: `{e}`", ephemeral=True)

        sold_embed = discord.Embed(
            title="⚠️ OFFER UPDATE — NO LONGER AVAILABLE",
            description=(
                f"The account **{format_offer_id(offer_number)} - {self.listing['title']}** has been sold and is no longer available.\n\n"
                "If you're interested in another account, return to the Accounts Shop and select a different offer."
            ),
            color=0xEF4444,
            timestamp=datetime.datetime.utcnow(),
        )
        sold_embed.set_footer(text="Pedrao22k Accounts Shop")

        notified_channels = 0
        try:
            interested = await get_interested_active_tickets(listing_id)
            for ticket, link in interested:
                # Idempotency: do not send the SOLD notice twice for the same
                # ticket/offer even if the command is retried.
                if link.get("sold_notified_at"):
                    continue
                channel = interaction.guild.get_channel(int(ticket["channel_id"])) if interaction.guild else None
                if not isinstance(channel, discord.TextChannel):
                    await close_persisted_purchase_ticket(int(ticket["channel_id"]))
                    continue
                try:
                    await channel.send(embed=sold_embed)
                    await mark_ticket_offer_sold(int(link["id"]), notified=True)
                    notified_channels += 1
                except Exception as e:
                    print(f"Could not send sold notice to {ticket['channel_id']}: {e}")
        except Exception as e:
            print(f"Sold interested-ticket notification error: {e}")

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ **{format_offer_id(offer_number)} - {self.listing['title']}** has been marked as sold and removed from the Accounts Shop. "
            f"Notified **{notified_channels}** active purchase ticket(s). Tickets remain open for other offers.",
            ephemeral=True,
        )


    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_sold(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("❌ Only the staff member who started this action can cancel it.", ephemeral=True)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Sold action cancelled.", embed=None, view=self)

async def get_discord_user_from_access_token(access_token: str):
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            if response.status != 200:
                raise RuntimeError("Discord authentication failed.")
            return await response.json()

async def create_or_reuse_purchase_ticket(buyer_id: int, listing: dict):
    category = bot.get_channel(TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        raise RuntimeError("Purchase ticket category was not found.")
    guild = category.guild
    buyer = guild.get_member(buyer_id)
    if buyer is None:
        try:
            buyer = await guild.fetch_member(buyer_id)
        except Exception:
            raise RuntimeError("Buyer is not a member of this Discord server.")

    listing_id = str(listing["id"])
    offer_number = int(listing["offer_number"])

    async with purchase_ticket_lock:
        ticket_row = await get_active_purchase_ticket(buyer_id)
        channel = None

        if ticket_row:
            candidate = guild.get_channel(int(ticket_row["channel_id"]))
            if isinstance(candidate, discord.TextChannel):
                channel = candidate
            else:
                # Stale DB row: the Discord channel was deleted outside the normal
                # Close Ticket flow. Close it in DB and allow a new ticket.
                await close_persisted_purchase_ticket(int(ticket_row["channel_id"]))
                ticket_row = None

        # Backward-compatible migration for a V5.58 ticket that already exists.
        if channel is None:
            for candidate in guild.text_channels:
                meta = parse_purchase_ticket_topic(candidate.topic)
                if meta and meta.get("buyer_id") == buyer_id:
                    channel = candidate
                    try:
                        ticket_row = await register_purchase_ticket(buyer_id, channel)
                    except Exception:
                        ticket_row = await get_active_purchase_ticket(buyer_id)
                    old_listing = await fetch_listing_by_id(str(meta.get("listing_id", "")))
                    if ticket_row and old_listing and not await get_ticket_offer(int(ticket_row["id"]), str(old_listing["id"])):
                        try:
                            await add_ticket_offer(int(ticket_row["id"]), old_listing)
                        except Exception as e:
                            print(f"Legacy purchase ticket offer migration error: {e}")
                    break

        created_ticket = False
        if channel is None:
            support_role = guild.get_role(SUPPORT_ROLE_ID)
            clean_user_name = re.sub(r"[^a-z0-9-]", "", buyer.name.lower().replace(" ", "-"))[:28] or str(buyer.id)[-6:]
            channel_name = f"buy-account-{clean_user_name}"[:100]
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                buyer: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
            support_role = guild.get_role(SUPPORT_ROLE_ID)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=purchase_ticket_topic(listing_id, offer_number, buyer_id),
                overwrites=overwrites,
                reason=f"Accounts Shop purchase ticket for {buyer}",
            )
            try:
                ticket_row = await register_purchase_ticket(buyer_id, channel)
            except Exception:
                try:
                    await channel.delete(reason="Purchase ticket persistence failed")
                except Exception:
                    pass
                raise
            created_ticket = True

        ticket_id = int(ticket_row["id"])
        existing_offer = await get_ticket_offer(ticket_id, listing_id)
        if existing_offer:
            return channel, True, True

        # Persist first to make rapid duplicate Contact Seller clicks idempotent.
        link = await add_ticket_offer(ticket_id, listing)
        try:
            embed = discord.Embed(
                title=f"{format_offer_id(offer_number)} - {listing['title']}",
                description=(
                    f"**Price:** {format_listing_price(listing)}\n"
                    f"**Buyer:** {buyer.mention}"
                    + ("\n\nThis ticket was created from the Accounts Shop." if created_ticket else "")
                ),
                color=0xF59E0B,
                timestamp=datetime.datetime.utcnow(),
            )
            embed.set_footer(text="Pedrao22k Accounts Shop")
            support_role = guild.get_role(SUPPORT_ROLE_ID)
            role_ping = support_role.mention if support_role else ""
            content = f"{buyer.mention} {role_ping}" if created_ticket else None
            await channel.send(content=content, embed=embed, view=PurchaseOfferActivityView())
            if created_ticket:
                await channel.send(view=CloseTicketView())
        except Exception:
            try:
                await remove_ticket_offer(ticket_id, listing_id)
            except Exception as rollback_error:
                print(f"Purchase ticket offer rollback error: {rollback_error}")
            raise

        return channel, not created_ticket, False

async def handle_discord_exchange(request):
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return api_json({"status": "error", "error": "Discord Activity authentication is not configured."}, status=503)
    try:
        payload = await request.json()
    except Exception:
        return api_json({"status": "error", "error": "Invalid request."}, status=400)
    code = str(payload.get("code", "")).strip()
    if not code:
        return api_json({"status": "error", "error": "Missing Discord authorization code."}, status=400)

    form = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
    }
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post("https://discord.com/api/oauth2/token", data=form) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not data.get("access_token"):
                print(f"Discord OAuth exchange error: {response.status} {str(data)[:300]}")
                return api_json({"status": "error", "error": "Discord authorization failed."}, status=401)
            return api_json({
                "access_token": data["access_token"],
                "token_type": data.get("token_type", "Bearer"),
                "expires_in": data.get("expires_in"),
                "scope": data.get("scope", ""),
            })

async def handle_contact_seller(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return api_json({"status": "error", "error": "Discord authentication is required."}, status=401)
    access_token = auth_header[7:].strip()
    try:
        discord_user = await get_discord_user_from_access_token(access_token)
    except Exception:
        return api_json({"status": "error", "error": "Discord authentication expired. Please try again."}, status=401)

    try:
        payload = await request.json()
    except Exception:
        return api_json({"status": "error", "error": "Invalid request."}, status=400)

    listing_id = str(payload.get("listing_id", "")).strip()
    offer_number = normalize_offer_number(payload.get("offer_number"))
    try:
        listing = await fetch_listing_by_id(listing_id, published_only=True) if listing_id else None
        if listing is None and offer_number is not None:
            listing = await fetch_listing_by_offer_number(offer_number, published_only=True)
        if not listing:
            return api_json({"status": "error", "error": "This account is no longer available."}, status=409)
        channel, reused_ticket, duplicate_offer = await create_or_reuse_purchase_ticket(int(discord_user["id"]), listing)
    except Exception as e:
        print(f"Contact Seller error: {e}")
        return api_json({"status": "error", "error": str(e)}, status=500)

    return api_json({
        "status": "ok",
        "offer_number": listing["offer_number"],
        "channel_id": str(channel.id),
        "guild_id": str(channel.guild.id),
        "channel_url": f"https://discord.com/channels/{channel.guild.id}/{channel.id}",
        "reused": reused_ticket,
        "reused_ticket": reused_ticket,
        "duplicate_offer": duplicate_offer,
        "offer_added": not duplicate_offer,
    })


async def handle_activity_context(request):
    """Resolve which public offer belongs to the Discord channel that launched the Activity.

    This endpoint exposes only public listing identifiers. The channel topic is
    written by this bot and is the source of the ticket -> offer mapping.
    """
    raw_channel_id = str(request.query.get("channel_id", "")).strip()
    if not raw_channel_id.isdigit():
        return api_json({"status": "ok", "offer_number": None, "listing_id": None})

    channel_id = int(raw_channel_id)
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            channel = None

    if not isinstance(channel, discord.TextChannel):
        return api_json({"status": "ok", "offer_number": None, "listing_id": None})

    meta = parse_activity_offer_topic(channel.topic)
    if not meta:
        return api_json({"status": "ok", "offer_number": None, "listing_id": None})

    return api_json({
        "status": "ok",
        "offer_number": int(meta["offer_number"]),
        "listing_id": str(meta["listing_id"]),
    })

async def handle_api_options(request):
    return api_json({"status": "ok"})

def api_json(data, *, status=200):
    return web.json_response(data, status=status, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Cache-Control": "no-store",
    })

class DirectPortalLauncherView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=None)
        upload_url = f"{BASE_WEB_URL}/upload?session={session_id}"
        self.add_item(Button(label="Open Seller Portal (WARZONE / MW4)", style=discord.ButtonStyle.link, url=upload_url, emoji="⚡"))

class MarketplaceLauncherView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Sell Call of Duty Account", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="sell_cod_account_btn")
    async def open_ticket_direct(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, "sell_account_ticket", cooldown=12.0):
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        sell_category = guild.get_channel(SELL_CATEGORY_ID)
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        if not isinstance(sell_category, discord.CategoryChannel):
            return await interaction.followup.send("❌ Seller ticket category was not found. Please contact staff.", ephemeral=True)

        clean_user_name = interaction.user.name.lower().replace(" ", "-")
        channel_name = f"🏷️・sell-{clean_user_name}"

        existing = await find_or_adopt_seller_ticket(guild, sell_category, interaction.user)
        if existing:
            # Make sure a restart/old session never leaves the seller with a dead portal button.
            try:
                await ensure_seller_portal_launcher(existing, int(interaction.user.id))
            except Exception as e:
                print(f"Seller portal refresh on reuse error for {existing.id}: {e}")
            return await interaction.followup.send(
                f"♻️ Your seller room is already open: {existing.mention}\nUse **Open Seller Portal** there to submit another account.",
                ephemeral=True,
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=False, attach_files=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)

        sell_ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=sell_category,
            overwrites=overwrites,
            topic=seller_ticket_topic(interaction.user.id),
        )
        session_id = str(uuid.uuid4())[:8]
        role_ping = support_role.mention if support_role else ""
        launcher_msg = await sell_ticket_channel.send(
            content=f"{interaction.user.mention} {role_ping}",
            embed=build_seller_portal_welcome_embed(interaction.user),
            view=DirectPortalLauncherView(session_id=session_id),
        )
        register_seller_portal_session(
            interaction.user.id, sell_ticket_channel.id, launcher_msg, session_id=session_id
        )
        await sell_ticket_channel.send(view=CloseTicketView())
        await interaction.followup.send(f"✅ Your seller room has been created: {sell_ticket_channel.mention}", ephemeral=True)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pedrao22k | Listing & Screenshots Portal</title>
    <style>
        :root {
            --gold-primary: #FFB800;
            --gold-glow: #F59E0B;
            --gold-hover: #D97706;
            --bg-dark: #070709;
            --card-bg: rgba(16, 17, 24, 0.90);
            --border-color: rgba(245, 158, 11, 0.35);
            --input-bg: rgba(22, 23, 31, 0.85);
        }
        * { box-sizing: border-box; }
        body {
            background-color: var(--bg-dark); color: #F8FAFC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; margin: 0; padding: 24px 16px; position: relative;
        }
        .container {
            background: var(--card-bg); backdrop-filter: blur(20px);
            border: 1px solid var(--border-color); border-radius: 20px;
            padding: 34px 28px; max-width: 580px; width: 100%; text-align: left;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.95), 0 0 45px rgba(245, 158, 11, 0.2);
        }
        .header-logo { display: flex; justify-content: center; align-items: center; margin-bottom: 12px; }
        .header-logo .lightning { font-size: 38px; color: var(--gold-primary); filter: drop-shadow(0 0 15px rgba(255, 184, 0, 0.9)); }
        h2 { margin: 0; color: #FFFFFF; text-align: center; font-size: 24px; font-weight: 800; margin-bottom: 24px; }
        h2 span { color: var(--gold-primary); }
        label { display: block; font-weight: 700; font-size: 12px; margin-bottom: 7px; color: #E2E8F0; text-transform: uppercase; letter-spacing: 0.8px; }
        input[type="text"], select, textarea {
            width: 100%; background: var(--input-bg); border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px; padding: 13px 15px; color: #FFFFFF; font-size: 14px; margin-bottom: 18px; outline: none;
        }
        input[type="text"]:focus, select:focus, textarea:focus { border-color: var(--gold-primary); background: rgba(26, 27, 36, 0.95); }
        .price-row { display: flex; gap: 10px; }
        .price-row input { flex: 2; }
        .price-row select { flex: 1; }
        
        /* تصميم خيارات الإنجازات (Checkboxes) */
        .checkbox-container {
            background: rgba(18, 19, 26, 0.7); border: 1px solid rgba(245, 158, 11, 0.25);
            border-radius: 12px; padding: 15px; margin-bottom: 18px;
        }
        .checkbox-title {
            font-size: 13px; font-weight: 800; color: var(--gold-primary); margin-bottom: 12px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .select-all-btn {
            background: rgba(245, 158, 11, 0.15); border: 1px solid var(--gold-primary); color: var(--gold-primary);
            font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; cursor: pointer; text-transform: uppercase;
        }
        .select-all-btn:hover { background: var(--gold-primary); color: #000; }
        .checkbox-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .checkbox-label {
            display: flex; align-items: center; gap: 8px; background: rgba(22, 23, 31, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.08); padding: 10px; border-radius: 8px; cursor: pointer;
            font-size: 13px; font-weight: 600; color: #F8FAFC; transition: 0.2s;
        }
        .checkbox-label:hover { border-color: var(--gold-primary); background: rgba(30, 31, 42, 0.95); }
        .checkbox-label input { accent-color: var(--gold-primary); width: 16px; height: 16px; cursor: pointer; }

        .dropzone {
            border: 2px dashed rgba(245, 158, 11, 0.45); border-radius: 14px; padding: 20px 15px;
            cursor: pointer; background: rgba(18, 19, 26, 0.65); text-align: center; margin-bottom: 12px;
        }
        .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 8px; margin-bottom: 14px; }
        .preview-item { position: relative; border-radius: 6px; overflow: hidden; border: 2px solid #333; background: #111; }
        .preview-item img { width: 100%; height: 60px; object-fit: cover; display: block; }
        
        .progress-box { display: none; margin-bottom: 20px; }
        .progress-header { display: flex; justify-content: space-between; font-size: 12px; font-weight: 700; margin-bottom: 6px; color: #CBD5E1; }
        .progress-bar-bg { width: 100%; height: 10px; background: #232530; border-radius: 6px; overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.06); }
        .progress-bar-fill { width: 0%; height: 100%; background: linear-gradient(90deg, #D97706, #FFB800); border-radius: 6px; transition: width 0.2s ease; box-shadow: 0 0 12px rgba(255, 184, 0, 0.6); }

        .btn {
            background: linear-gradient(135deg, #FFB800 0%, #D97706 100%); color: #050507; padding: 15px 28px;
            border: none; border-radius: 10px; font-size: 15px; font-weight: 800; cursor: pointer; width: 100%;
            text-transform: uppercase; letter-spacing: 0.8px; box-shadow: 0 4px 25px rgba(245, 158, 11, 0.45);
        }
        .btn:disabled { background: #252631; color: #64748B; cursor: not-allowed; box-shadow: none; }
    </style>
</head>
<body>
    <div class="container">
        <div id="formScreen">
            <div class="header-logo"><span class="lightning">⚡</span></div>
            <h2>PEDRAO22K <span>SELLER PORTAL</span></h2>

            <label for="offerTitle">Offer Title</label>
            <input type="text" id="offerTitle" placeholder="e.g. Wz Top 250 Season 5 + Rare Black Cells" required>

            <label for="price">Asking Price & Currency</label>
            <div class="price-row">
                <input type="text" id="price" inputmode="decimal" placeholder="e.g. 150" oninput="this.value = this.value.replace(/[^0-9.]/g, '')" required>
                <select id="currency">
                    <option value="USD">USD ($)</option>
                    <option value="EUR">EUR (€)</option>
                </select>
            </div>

            <!-- Optional account highlights -->
            <div class="checkbox-container">
                <div class="checkbox-title">
                    <span>DOES YOUR ACCOUNT HAVE ANY OF THESE ITEMS?</span>
                    <button type="button" class="select-all-btn" onclick="toggleSelectAll(this)">Select All</button>
                </div>
                <div class="checkbox-grid">
                    <label class="checkbox-label"><input type="checkbox" name="accountItem" value="Top 250"> Top 250</label>
                    <label class="checkbox-label"><input type="checkbox" name="accountItem" value="Nukes"> Nukes</label>
                    <label class="checkbox-label"><input type="checkbox" name="accountItem" value="Iridescent"> Iridescent</label>
                </div>
            </div>

            <label for="desc">Offer Description & Details</label>
            <textarea id="desc" rows="4" placeholder="Detail your account: platform, rank, camos, access..." required></textarea>

            <!-- 1. الصورة الأساسية (Cover Thumbnail) -->
            <label>⭐ Primary Cover Thumbnail (Main Image)</label>
            <div class="dropzone" onclick="document.getElementById('coverInput').click()">
                <div style="font-size: 26px; color: #FFB800;">⚡</div>
                <div id="coverText" style="font-weight: 700; color: #FFF; font-size: 13px;">Click to Upload Primary Cover Image</div>
            </div>
            <input type="file" id="coverInput" accept="image/*" style="display:none;" onchange="handleCoverSelection(this.files[0])">
            <div class="preview-grid" id="coverPreview"></div>

            <!-- 2. الصور الثانوية (Gallery) -->
            <label>📸 OFFER GALLERY CAPTURES</label>
            <div class="dropzone" onclick="document.getElementById('secondaryInput').click()">
                <div style="font-size: 26px; color: #FFB800;">📸</div>
                <div id="secondaryText" style="font-weight: 700; color: #FFF; font-size: 13px;">Click to upload gallery screenshots (Max 40)</div>
            </div>
            <input type="file" id="secondaryInput" multiple accept="image/*" style="display:none;" onchange="handleSecondarySelection(this.files)">
            <div class="preview-grid" id="secondaryPreview"></div>

            <div class="progress-box" id="progressBox">
                <div class="progress-header">
                    <span id="progressText">Uploading Images...</span>
                    <span id="progressPercent" style="color: #FFB800;">0%</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="progressBarFill"></div>
                </div>
            </div>

            <button id="submitBtn" class="btn" disabled onclick="submitFinalListing()">🚀 Submit Listing to Staff</button>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const session = urlParams.get('session');
        let coverFile = null;
        let secondaryFiles = [];
        let isCoverUploaded = false;

        function toggleSelectAll(btn) {
            const checkboxes = document.querySelectorAll('input[name="accountItem"]');
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            checkboxes.forEach(cb => cb.checked = !allChecked);
            btn.innerText = allChecked ? "Select All" : "Deselect All";
        }

        function checkSubmitReady() {
            const submitBtn = document.getElementById('submitBtn');
            if (coverFile && secondaryFiles.length > 0 && isCoverUploaded) {
                submitBtn.disabled = false;
            } else {
                submitBtn.disabled = true;
            }
        }

        function handleCoverSelection(file) {
            if (!file || !file.type.startsWith('image/')) return;
            coverFile = file;
            
            const grid = document.getElementById('coverPreview');
            grid.innerHTML = `<div class="preview-item"><img src="${URL.createObjectURL(file)}"></div>`;
            document.getElementById('coverText').innerText = `✨ Cover Loaded: ${file.name}`;
            document.getElementById('coverText').style.color = '#FFB800';

            uploadImagesDirectly(file, true);
        }

        function fileFingerprint(file) {
            return `${file.name}|${file.size}|${file.lastModified}`;
        }

        function handleSecondarySelection(files) {
            const existing = new Set(secondaryFiles.map(fileFingerprint));
            const coverFingerprint = coverFile ? fileFingerprint(coverFile) : null;
            const accepted = [];
            let skipped = 0;

            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                if (!file.type.startsWith('image/')) continue;
                const fingerprint = fileFingerprint(file);
                if (fingerprint === coverFingerprint || existing.has(fingerprint)) {
                    skipped += 1;
                    continue;
                }
                existing.add(fingerprint);
                secondaryFiles.push(file);
                accepted.push(file);
            }
            if (secondaryFiles.length === 0) return;

            const grid = document.getElementById('secondaryPreview');
            grid.innerHTML = '';
            secondaryFiles.forEach(file => {
                const item = document.createElement('div');
                item.className = 'preview-item';
                item.innerHTML = `<img src="${URL.createObjectURL(file)}">`;
                grid.appendChild(item);
            });

            document.getElementById('secondaryText').innerText = skipped > 0
                ? `✨ ${secondaryFiles.length} Gallery Screenshots Loaded • ${skipped} Duplicate Skipped`
                : `✨ ${secondaryFiles.length} Gallery Screenshots Loaded`;
            document.getElementById('secondaryText').style.color = '#FFB800';

            accepted.forEach(file => uploadImagesDirectly(file, false));
        }

        function uploadImagesDirectly(file, isCover) {
            if (!session) {
                alert("Session missing. Please reopen from Discord ticket.");
                return;
            }

            const formData = new FormData();
            formData.append("session", session);
            formData.append("is_cover", isCover ? "1" : "0");
            formData.append("files", file);

            const progressBox = document.getElementById('progressBox');
            const progressBarFill = document.getElementById('progressBarFill');
            const progressPercent = document.getElementById('progressPercent');
            const progressText = document.getElementById('progressText');

            progressBox.style.display = "block";
            progressBarFill.style.width = "0%";
            progressPercent.innerText = "0%";
            progressText.innerText = isCover ? "Uploading Primary Cover..." : "Uploading Gallery Screenshots...";

            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/api/upload_images_only", true);

            xhr.upload.onprogress = function(e) {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    progressBarFill.style.width = percent + "%";
                    progressPercent.innerText = percent + "%";
                }
            };

            xhr.onload = function() {
                try {
                    const res = JSON.parse(xhr.responseText);
                    if (xhr.status === 200 && res.status === "ok") {
                        progressBarFill.style.width = "100%";
                        progressPercent.innerText = "100%";
                        progressText.innerText = "✨ Upload Complete!";
                        if (isCover) isCoverUploaded = true;
                        checkSubmitReady();

                        setTimeout(() => {
                            progressBox.style.display = "none";
                        }, 800);
                    } else {
                        alert(res.error || "Upload failed.");
                    }
                } catch (e) {
                    alert("Server error.");
                }
            };
            xhr.send(formData);
        }

        async function submitFinalListing() {
            const offerTitle = document.getElementById('offerTitle').value.trim();
            const price = document.getElementById('price').value.trim();
            const currency = document.getElementById('currency').value;
            const desc = document.getElementById('desc').value.trim();

            const selectedItems = [];
            document.querySelectorAll('input[name="accountItem"]:checked').forEach(cb => {
                selectedItems.push(cb.value);
            });
            const itemsString = selectedItems.length > 0 ? selectedItems.join(' • ') : 'None';

            if (!offerTitle || !price || !desc || !coverFile || secondaryFiles.length === 0) {
                alert("Please fill in all fields, upload primary cover, and at least one gallery image.");
                return;
            }

            const submitBtn = document.getElementById('submitBtn');
            submitBtn.disabled = true;
            submitBtn.innerText = "⏳ Processing...";

            const progressBox = document.getElementById('progressBox');
            const progressBarFill = document.getElementById('progressBarFill');
            const progressPercent = document.getElementById('progressPercent');
            const progressText = document.getElementById('progressText');
            
            progressBox.style.display = "block";
            progressBarFill.style.width = "100%";
            progressPercent.innerText = "100%";
            progressText.innerText = "⚡ Dispatched to Discord Staff...";

            const formData = new FormData();
            formData.append("session", session);
            formData.append("offerTitle", offerTitle);
            formData.append("price", price);
            formData.append("currency", currency);
            formData.append("items", itemsString);
            formData.append("description", desc);

            try {
                const res = await fetch("/api/finalize_listing", { method: "POST", body: formData });
                const json = await res.json();
                if (json.status === "ok") {
                    document.getElementById('formScreen').innerHTML = '<div style="text-align:center; padding: 40px;"><h2 style="color:#10B981">🎉 SUBMITTED SUCCESSFULLY!</h2><p style="color:#CBD5E1;">Your listing with all proofs has been sent to staff. You can close this window and return to Discord.</p></div>';
                } else {
                    alert(json.error || "Submission failed.");
                    submitBtn.disabled = false;
                    submitBtn.innerText = "🚀 Submit Listing to Staff";
                }
            } catch (e) {
                alert("Network error.");
                submitBtn.disabled = false;
                submitBtn.innerText = "🚀 Submit Listing to Staff";
            }
        }
    </script>
</body>
</html>
"""

async def ping_handler(request):
    return web.Response(text="Pedrao22k Bot is Online 24/7!", status=200)

async def handle_web_page(request):
    session_id = str(request.query.get("session", "")).strip()
    session_info = active_web_sessions.get(session_id)
    if session_info and not session_info.get("finalized"):
        channel = bot.get_channel(int(session_info.get("channel_id", 0) or 0))
        if isinstance(channel, discord.TextChannel):
            meta = parse_seller_ticket_topic(channel.topic)
            if meta and not meta.get("hold_open"):
                try:
                    # Seller actively opened the form. Give them enough time to
                    # finish it instead of deleting the ticket mid-submission.
                    await set_seller_ticket_state(
                        channel, int(meta["seller_id"]),
                        close_at=int(time.time()) + SELLER_PORTAL_ACTIVE_GRACE_SECONDS,
                        hold_open=False,
                        reason="Seller Portal opened; postpone automatic close",
                    )
                except Exception as e:
                    print(f"Seller portal open grace error: {e}")
    return web.Response(text=HTML_PAGE, content_type="text/html")

async def handle_upload_images_only(request):
    try:
        reader = await request.multipart()
        session_id = None
        is_cover = "0"
        saved_path = None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "session":
                session_id = (await part.read()).decode('utf-8')
            elif part.name == "is_cover":
                is_cover = (await part.read()).decode('utf-8')
            elif part.name == "files":
                filename = part.filename
                if filename:
                    ext = os.path.splitext(filename)[1].lower()
                    clean_name = f"{uuid.uuid4().hex}{ext}"
                    file_path = os.path.join("uploaded_screenshots", clean_name)
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                    saved_path = file_path

        if not session_id or session_id not in active_web_sessions:
            return web.json_response({"status": "error", "error": "Session expired or bot restarted."}, status=400)

        if saved_path:
            if is_cover == "1":
                active_web_sessions[session_id]["cover_file"] = saved_path
            else:
                active_web_sessions[session_id]["secondary_files"].append(saved_path)

        return web.json_response({"status": "ok"})
    except Exception as e:
        print(f"Upload error: {e}")
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def _handle_finalize_listing(request, data):
    try:
        session_id = data.get("session")
        offer_title = data.get("offerTitle", "Verified COD Account")
        price = data.get("price", "")
        currency = data.get("currency", "USD")
        items_list = data.get("items", "None")
        description = data.get("description", "")

        # Persist every Seller Portal highlight. The legacy `category` field
        # remains populated with the first supported highlight so older Shop
        # builds and existing integrations keep working during rollout.
        selected_highlights = {
            item.strip().lower()
            for item in str(items_list).split("•")
            if item.strip() and item.strip().lower() != "none"
        }
        highlight_category_map = (
            ("top 250", "TOP_250"),
            ("nukes", "NUKES"),
            ("iridescent", "IRIDESCENT"),
        )
        categories = [
            category_code
            for highlight_label, category_code in highlight_category_map
            if highlight_label in selected_highlights
        ]
        category = categories[0] if categories else None

        if not session_id or session_id not in active_web_sessions:
            return web.json_response({"status": "error", "error": "Session expired."}, status=400)
        if currency not in ("USD", "EUR"):
            return web.json_response({"status": "error", "error": "Please select USD or EUR."}, status=400)
        try:
            price_value = float(price)
            if price_value <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            return web.json_response({"status": "error", "error": "Please enter a valid price."}, status=400)

        session_info = active_web_sessions[session_id]
        cover_path = session_info.get("cover_file")
        secondary_paths = session_info.get("secondary_files", [])
        seller_id = session_info["seller_id"]
        channel_id = session_info["channel_id"]
        launcher_msg = session_info["launcher_msg"]

        ticket_channel = bot.get_channel(channel_id)
        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        support_role = ticket_channel.guild.get_role(SUPPORT_ROLE_ID) if ticket_channel else None
        seller = bot.get_user(seller_id) or await bot.fetch_user(seller_id)

        if not ticket_channel or not review_channel:
            return web.json_response({"status": "error", "error": "The seller ticket or staff review channel is unavailable. Please contact staff."}, status=503)

        if session_info.get("finalized"):
            return web.json_response({"status": "ok", "count": len(session_info.get("discord_cdn_urls", []))})

        if session_info.get("all_paths") is None:
            all_paths = []
            if cover_path and os.path.isfile(cover_path):
                all_paths.append(cover_path)
            for sp in secondary_paths:
                if os.path.isfile(sp):
                    all_paths.append(sp)
            # Avoid storing the cover (or any screenshot) twice when the same
            # file is selected more than once in the Seller Portal.
            all_paths = dedupe_file_paths_by_content(all_paths)
            session_info["all_paths"] = all_paths
        all_paths = session_info["all_paths"]

        if not cover_path or len(all_paths) < 2:
            return web.json_response({"status": "error", "error": "Upload a cover image and at least one different gallery image."}, status=400)

        # A stable UUID per portal session prevents duplicate records on a retry.
        listing_id = session_info.get("listing_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"pedrao22k-listing:{session_id}"))
        if not session_info.get("listing_id"):
            try:
                await create_supabase_listing(listing_id, seller_id, channel_id, offer_title, price_value, currency, category, categories, description, all_paths)
                session_info["listing_id"] = listing_id
            except Exception as e:
                print(f"Supabase listing creation error: {e}")
                return web.json_response({"status": "error", "error": "Could not save your listing and screenshots to the shop database. Please contact staff before retrying."}, status=502)

        saved_listing = await fetch_listing_by_id(listing_id)
        submitted_offer_number = normalize_offer_number(saved_listing.get("offer_number")) if saved_listing else None
        submitted_offer_id = format_offer_id(submitted_offer_number) if submitted_offer_number is not None else "Pending ID"

        clean_price_num = str(price_value)
        discord_cdn_urls = session_info["discord_cdn_urls"]
        uploaded_paths = set(session_info["discord_uploaded_paths"])
        for fp in all_paths:
            if fp in uploaded_paths:
                continue
            if not os.path.isfile(fp):
                return web.json_response({"status": "error", "error": "A screenshot is missing during submission. Please contact staff so we can recover the listing."}, status=409)
            batch_msg = await review_channel.send(content=f"📸 *Proof for {seller.mention}:*", file=discord.File(fp))
            for att in batch_msg.attachments:
                discord_cdn_urls.append(att.url)
            session_info["discord_uploaded_paths"].append(fp)
            try:
                os.remove(fp)
            except OSError:
                pass

        submitted_embed = build_seller_status_embed(
            status="PENDING_REVIEW",
            seller_mention=seller.mention,
            offer_id=submitted_offer_id,
            offer_title=offer_title,
            price_str=f"{clean_price_num} {currency}",
            highlights=items_list,
            screenshots=f"{len(discord_cdn_urls)} proofs uploaded",
            avatar_url=(seller.display_avatar.url if seller.display_avatar else None),
        )

        admin_embed = discord.Embed(
            title=f"📥 {submitted_offer_id} — {offer_title}",
            description=f"**Seller:** {seller.mention} (`{seller.id}`)\n**Ticket Channel:** {ticket_channel.mention}",
            color=0xF59E0B,
            timestamp=datetime.datetime.utcnow()
        )
        admin_embed.add_field(name="💰 Asking Price", value=f"{clean_price_num} {currency}", inline=False)
        admin_embed.add_field(name="🗂️ Shop Category", value=(category.replace("_", " ") if category else "All / Uncategorized"), inline=True)
        admin_embed.add_field(name="🌟 Account Highlights", value=f"{items_list}", inline=False)
        admin_embed.add_field(name="📋 Account Details", value=description[:1024], inline=False)
        if discord_cdn_urls:
            admin_embed.set_image(url=discord_cdn_urls[0])

        # Every listing gets its own status message. The portal launcher stays
        # untouched so the seller can submit another account with one click.
        submission_msg = await ticket_channel.send(embed=submitted_embed)
        await persist_seller_status_message_id(listing_id, submission_msg.id)

        if not session_info.get("review_dispatched"):
            role_ping = support_role.mention if support_role else "@here"
            approval_view = AdminApprovalView(
                seller=seller,
                embed_data=admin_embed,
                ticket_channel=ticket_channel,
                images=discord_cdn_urls,
                launcher_msg=submission_msg,
                offer_title=offer_title,
                price_num=clean_price_num,
                currency=currency,
                items_list=items_list,
                description=description,
                count_str=f"{len(discord_cdn_urls)} proofs",
                listing_id=listing_id
            )
            await review_channel.send(
                content=f"🔔 {role_ping} **New Account Submission (Cover Thumbnail Selected):**",
                embed=admin_embed,
                view=approval_view
            )
            session_info["review_dispatched"] = True

        try:
            await mark_seller_ticket_submission_active(ticket_channel, seller_id)
        except Exception as e:
            print(f"Seller ticket submission state error: {e}")

        session_info["finalized"] = True
        try:
            await rotate_seller_portal_session(ticket_channel, seller, launcher_msg)
        except Exception as e:
            print(f"Seller portal rotation error: {e}")

        return web.json_response({
            "status": "ok",
            "count": len(discord_cdn_urls),
            "offer_number": submitted_offer_number,
        })
    except Exception as e:
        print(f"Finalize error: {e}")
        return web.json_response({"status": "error", "error": "Submission could not be completed. Please retry once; if it continues, contact staff."}, status=500)

async def handle_finalize_listing(request):
    try:
        data = await request.post()
    except Exception:
        return web.json_response({"status": "error", "error": "Invalid submission data."}, status=400)
    session_id = data.get("session")
    session_info = active_web_sessions.get(session_id)
    if not session_info:
        return web.json_response({"status": "error", "error": "Session expired. Please reopen the seller portal."}, status=400)
    # Serialize repeated clicks/retries for this portal session.
    async with session_info["finalize_lock"]:
        return await _handle_finalize_listing(request, data)

async def session_cleaner_task():
    while True:
        await asyncio.sleep(300)
        now = datetime.datetime.utcnow()
        expired = []
        for sid, data in list(active_web_sessions.items()):
            age = (now - data["created_at"]).total_seconds()
            channel_exists = bot.get_channel(int(data.get("channel_id", 0) or 0)) is not None
            if (data.get("finalized") and age > 3600) or (not channel_exists and age > 300):
                expired.append(sid)
        for sid in expired:
            active_web_sessions.pop(sid, None)

async def start_web_server():
    app = web.Application(client_max_size=300 * 1024 * 1024)
    app.router.add_get("/", ping_handler)
    app.router.add_get("/upload", handle_web_page)
    app.router.add_post("/api/upload_images_only", handle_upload_images_only)
    app.router.add_post("/api/finalize_listing", handle_finalize_listing)
    app.router.add_post("/api/discord/exchange", handle_discord_exchange)
    app.router.add_post("/api/contact-seller", handle_contact_seller)
    app.router.add_get("/api/activity-context", handle_activity_context)
    app.router.add_options("/api/discord/exchange", handle_api_options)
    app.router.add_options("/api/contact-seller", handle_api_options)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    print(f"🌐 Seller Portal Web Engine online on 0.0.0.0:{WEB_PORT}!")

class FeedbackModal(Modal, title="Rate Your Experience"):
    def __init__(self):
        super().__init__()
        self.rating_input = TextInput(label="Rating (1 to 5 Stars)", placeholder="e.g. 5 or ⭐⭐⭐⭐⭐", required=True, max_length=10)
        self.review_input = TextInput(label="Your Feedback Review", style=discord.TextStyle.paragraph, placeholder="How was the service?", required=True, max_length=500)
        self.add_item(self.rating_input)
        self.add_item(self.review_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not await allow_single_interaction(interaction, "feedback_submit", cooldown=30.0):
            return
        stars = self.rating_input.value.strip()
        comment = self.review_input.value.strip()
        vouch_channel = interaction.guild.get_channel(VOUCH_CHANNEL_ID)
        vouch_embed = discord.Embed(title="⭐ NEW VERIFIED CLIENT REVIEW", description=f"**Client:** {interaction.user.mention}\n**Rating:** `{stars}`\n\n> {comment}", color=0xF59E0B, timestamp=datetime.datetime.utcnow())
        vouch_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        vouch_embed.set_footer(text="Pedrao22k Verified Customer Review")
        if vouch_channel:
            await vouch_channel.send(embed=vouch_embed)
        await interaction.response.send_message("🎉 **Thank you so much for your feedback!**", ephemeral=True)

class FeedbackView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Leave Feedback ⭐", style=discord.ButtonStyle.success, emoji="✍️", custom_id="leave_vouch_btn")
    async def open_feedback_modal(self, interaction: discord.Interaction, button: Button):
        if not await allow_single_interaction(interaction, "open_feedback_modal", cooldown=6.0):
            return
        await interaction.response.send_modal(FeedbackModal())

persistent_views_registered = False
background_tasks_started = False
slash_commands_synced = False

@bot.event
async def on_ready():
    global persistent_views_registered, background_tasks_started, slash_commands_synced
    if not persistent_views_registered:
        bot.add_view(TicketLauncherView())
        bot.add_view(CloseTicketView())
        bot.add_view(MarketplaceLauncherView())
        bot.add_view(FeedbackView())
        bot.add_view(MarketplaceCarouselView(images=[], embed_data=discord.Embed()))
        bot.add_view(ShopLaunchView())
        bot.add_view(PurchaseOfferActivityView())
        bot.add_view(SellerApprovedActivityView())
        persistent_views_registered = True
    if not background_tasks_started:
        bot.loop.create_task(start_web_server())
        bot.loop.create_task(session_cleaner_task())
        bot.loop.create_task(seller_ticket_autoclose_task())
        background_tasks_started = True
    try:
        await ensure_shop_entry_message()
        await refresh_purchase_ticket_activity_buttons()
        await refresh_seller_portal_launchers()
    except Exception as e:
        print(f"Accounts Shop Activity setup error: {e}")

    if not slash_commands_synced:
        try:
            category = bot.get_channel(TICKET_CATEGORY_ID)
            if isinstance(category, discord.CategoryChannel):
                guild_obj = discord.Object(id=category.guild.id)
                bot.tree.copy_global_to(guild=guild_obj)
                synced = await bot.tree.sync(guild=guild_obj)
                print(f"✅ Synced {len(synced)} slash command(s) to guild {category.guild.id}.")
            else:
                synced = await bot.tree.sync()
                print(f"✅ Synced {len(synced)} global slash command(s).")
            slash_commands_synced = True
        except Exception as e:
            print(f"Slash command sync error: {e}")
    print(f"Logged in as {bot.user.name} | Railway Cloud Engine Online 24/7!")

@bot.tree.command(name="sold", description="Mark a published Accounts Shop offer as sold.")
@app_commands.describe(account_id="Optional account ID, for example 01#")
@app_commands.default_permissions(administrator=True)
async def sold_command(interaction: discord.Interaction, account_id: Optional[str] = None):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("❌ This command can only be used inside the server.", ephemeral=True)
    if not is_staff_member(interaction.user):
        return await interaction.response.send_message("❌ This command is restricted to staff.", ephemeral=True)

    source_channel_id = interaction.channel.id if isinstance(interaction.channel, discord.TextChannel) else None
    offer_number = normalize_offer_number(account_id)

    if isinstance(interaction.channel, discord.TextChannel):
        ticket_row = await get_active_ticket_by_channel(interaction.channel.id)
        if ticket_row:
            active_offers = await get_ticket_offers(int(ticket_row["id"]), active_only=True)
            if offer_number is None:
                if len(active_offers) == 1:
                    offer_number = int(active_offers[0]["offer_number"])
                elif len(active_offers) > 1:
                    ids = ", ".join(format_offer_id(int(x["offer_number"])) for x in active_offers)
                    return await interaction.response.send_message(
                        f"⚠️ This ticket contains multiple available offers: **{ids}**. Use `/sold` and provide the exact account ID, for example `02#`.",
                        ephemeral=True,
                    )

    if offer_number is None:
        return await interaction.response.send_message(
            "❌ No account ID was detected. Provide an ID such as `01#`.",
            ephemeral=True,
        )

    try:
        listing = await fetch_listing_by_offer_number(offer_number)
    except Exception as e:
        return await interaction.response.send_message(f"❌ Could not load {format_offer_id(offer_number)}: `{e}`", ephemeral=True)
    if not listing:
        return await interaction.response.send_message(f"❌ Account {format_offer_id(offer_number)} was not found.", ephemeral=True)
    if listing.get("status") == "SOLD":
        return await interaction.response.send_message(f"⚠️ Account {format_offer_id(offer_number)} is already marked as sold.", ephemeral=True)

    embed = discord.Embed(
        title=f"Mark {format_offer_id(offer_number)} as sold?",
        description=(
            f"**{format_offer_id(offer_number)} - {listing['title']}**\n\n"
            "This will remove the account from the Accounts Shop and notify every active purchase ticket interested in this offer. Other offers and tickets will remain open."
        ),
        color=0xEF4444,
    )
    await interaction.response.send_message(
        embed=embed,
        view=SoldConfirmationView(interaction.user.id, listing, source_channel_id),
        ephemeral=True,
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def testwelcome(ctx):
    channel = ctx.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return await ctx.send("❌ Welcome channel not found.")
    embed = build_welcome_embed(ctx.author, ctx.guild)
    await channel.send(content=f"👋 Welcome to the server, {ctx.author.mention}!", embed=embed)
    await ctx.send(f"✅ Welcome message sent successfully to {channel.mention}!")

@bot.command()
async def pay(ctx):
    embed = discord.Embed(
        title="💳 PEDRAO22K. | OFFICIAL PAYMENT GATEWAY",
        description=(
            "We strictly accept **Cryptocurrency** payments to guarantee privacy, speed, and safety.\n\n"
            "⚠️ **Important Payment Notes:**\n"
            "• Make sure you select the correct network before sending.\n"
            "• Once sent, upload the **Transaction ID / Screenshot** in this ticket.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xF59E0B
    )
    code_block = "```"
    embed.add_field(name="🟢 USDT (TRC-20) [Recommended]", value=f"{code_block}text\n{CRYPTO_ADDRESSES['USDT_TRC20']}\n{code_block}", inline=False)
    embed.add_field(name="🟡 USDT (BEP-20 / BSC)", value=f"{code_block}text\n{CRYPTO_ADDRESSES['USDT_BEP20']}\n{code_block}", inline=False)
    embed.add_field(name="⚪ Litecoin (LTC) [Low Fee]", value=f"{code_block}text\n{CRYPTO_ADDRESSES['LTC']}\n{code_block}", inline=False)
    embed.add_field(name="🟠 Bitcoin (BTC)", value=f"{code_block}text\n{CRYPTO_ADDRESSES['BTC']}\n{code_block}", inline=False)
    embed.set_footer(text="Pedrao22k. | Always double check the address before transferring")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def complete(ctx):
    await ctx.message.delete()
    current_channel = ctx.channel
    if not current_channel.name.startswith("✅"):
        clean_name = current_channel.name.replace("🎫・", "").replace("🏷️・", "").replace("🛒・", "")
        new_name = f"✅・{clean_name}"
        await current_channel.edit(name=new_name)

    embed = discord.Embed(
        title="🎉 ORDER COMPLETED SUCCESSFULLY!",
        description=(
            "Thank you for choosing **Pedrao22k Services**!\n\n"
            "Your order has been fully completed by our professional team.\n\n"
            "⭐ **Leave a Review:**\n"
            "Please click **'Leave Feedback'** below to leave your review and vouch for us in:\n"
            "> **`#⭐︲vouches-feedback`**"
        ),
        color=0x10B981
    )
    embed.set_footer(text="Pedrao22k. | Fast • Secure • Competitive")
    view = FeedbackView()
    view.add_item(Button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn"))
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_ticket(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="⚡ PEDRAO22K. | OFFICIAL ORDERS & SUPPORT",
        description=(
            "Welcome to **Pedrao22k Services**. We provide fast, reliable, and completely private gaming solutions.\n\n"
            "### 👑 Available Departments:\n"
            "> 🏆 **Ranked Boosting** — Top 250, Iridescent, Duo Queue, Wins\n"
            "> 🎨 **Camo Services** — Mastery Camos, Weapon Leveling, Challenges\n"
            "> 🛒 **Marketplace** — Buy verified & secure gaming accounts\n"
            "> 💬 **General Support** — Questions, custom requests, & consultations\n\n"
            "🔒 *Select a category from the dropdown menu below to begin your order:*"
        ),
        color=0xF59E0B
    )
    if ctx.guild.icon:
        embed.set_author(name="Pedrao22k Services", icon_url=ctx.guild.icon.url)
        embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.set_footer(text="Pedrao22k. | Fast Delivery • 100% Secure • 24/7 Response")
    await ctx.send(embed=embed, view=TicketLauncherView())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_market(ctx):
    await ctx.message.delete()
    embed = discord.Embed(
        title="⚡ PEDRAO22K. | SELLER SUBMISSION PORTAL",
        description=(
            "Want to list your personal Call of Duty / Warzone account for sale in our verified marketplace?\n\n"
            "### 📋 How it works:\n"
            "1. Click the button below to open your private seller channel.\n"
            "2. Fill in your offer title, description & price in a single window.\n"
            "3. Upload Cover Image and Secondary Screenshots.\n"
            "4. Staff will review and verify before publishing to the marketplace.\n\n"
            "Click below to get started!"
        ),
        color=0xF59E0B
    )
    if ctx.guild.icon:
        guild_icon_url = ctx.guild.icon.url
        embed.set_author(name="Pedrao22k Marketplace", icon_url=guild_icon_url)
    embed.set_footer(text="Pedrao22k. | Verified Seller Hub")
    await ctx.send(embed=embed, view=MarketplaceLauncherView())

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable. Configure it in Railway.")
bot.run(TOKEN)
