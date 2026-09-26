import discord
from discord.ext import commands
from discord.ui import Button, View, Select, Modal, TextInput
import asyncio
import io
import datetime
import os
import uuid
from aiohttp import web

# ======================== بيانات السيرفر والتصنيفات ========================
TOKEN = "MTU1MjYzNzE5ODU2NDcyMDY0Mg.GvL5lw.gphQoQCUDDY70PZRCdkYe_M3YZVDCK-tHMUzgc"

WELCOME_CHANNEL_ID = 1552627900191219752        # آيدي روم welcome
SUPPORT_ROLE_ID = 1552628903481184336            # آيدي رتبة Admin
TICKET_CATEGORY_ID = 1552642061608419408         # تصنيف تذاكر الطلبات العامة (Tickets ✅)
SELL_CATEGORY_ID = 1552642160992591892           # تصنيف تذاكر بيع الحسابات
TICKET_LOGS_CHANNEL_ID = 1552640603639259207       # روم حفظ سجلات التذاكر المحذوفة
MARKETPLACE_CHANNEL_ID = 1552628139618734170     # روم المعروضات accounts-for-sale
REVIEW_CHANNEL_ID = 1552643577547456564          # روم مراجعة الإدارة
VOUCH_CHANNEL_ID = 1552628000000000000           # آيدي روم الفيدباك (vouches-feedback)

# إعدادات واجهة الويب على Railway
WEB_PORT = int(os.environ.get("PORT", 8080))
BASE_WEB_URL = "https://cod-ticket-bot-production.up.railway.app"

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

os.makedirs("uploaded_screenshots", exist_ok=True)
active_web_sessions = {}

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
    if message.author.bot:
        return

    # قفل الشات: مسح أي رسالة نصية يرسلها البائع في تذكرة البيع لمنع التخريب
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
        await interaction.response.send_message("⏳ **Archiving transcript and deleting channel in 5 seconds...**")
        channel = interaction.channel

        log_text = "=== PEDRAO22K. TICKET TRANSCRIPT ===\n"
        log_text += f"Ticket Name: {channel.name}\n"
        log_text += f"Closed by: {interaction.user} ({interaction.user.id})\n"
        log_text += f"Closed At: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        log_text += "====================================\n\n"

        async for message in channel.history(limit=500, oldest_first=True):
            timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
            content = message.clean_content
            if message.attachments:
                attachments_urls = " [Attachments: " + ", ".join([a.url for a in message.attachments]) + "]"
                content += attachments_urls
            log_text += f"[{timestamp}] {message.author}: {content}\n"

        transcript_file = discord.File(io.BytesIO(log_text.encode('utf-8')), filename=f"transcript-{channel.name}.txt")

        logs_channel = interaction.guild.get_channel(TICKET_LOGS_CHANNEL_ID)
        if logs_channel:
            log_embed = discord.Embed(
                title="📑 TICKET CLOSED & ARCHIVED",
                description=f"Ticket **#{channel.name}** was archived.",
                color=0xEF4444,
                timestamp=datetime.datetime.utcnow()
            )
            log_embed.add_field(name="Closed By", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
            log_embed.add_field(name="Channel ID", value=f"`{channel.id}`", inline=True)
            log_embed.set_footer(text="Pedrao22k Audit Logs")
            await logs_channel.send(embed=log_embed, file=transcript_file)

        await asyncio.sleep(5)
        await channel.delete()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_close(self, interaction: discord.Interaction, button: Button):
        await interaction.message.delete()
        await interaction.response.send_message("❌ Ticket closure cancelled.", ephemeral=True)

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket_prompt(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="⚠️ Close Ticket Confirmation",
            description="Are you sure you want to close this ticket?\nA full transcript will be automatically saved to staff logs.",
            color=0xF59E0B
        )
        await interaction.response.send_message(embed=embed, view=ConfirmCloseView())

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

# ======================== نافذة سبب الرفض ========================
class RejectReasonModal(Modal, title="Listing Rejection Reason"):
    def __init__(self, seller: discord.User, ticket_channel: discord.TextChannel):
        super().__init__()
        self.seller = seller
        self.ticket_channel = ticket_channel
        self.reason_input = TextInput(
            label="Reason for Declining",
            style=discord.TextStyle.paragraph,
            placeholder="e.g. Nicknames visible in screenshots, inaccurate pricing, or blurry images.",
            required=True,
            max_length=500
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_input.value.strip()
        await interaction.response.send_message(f"✅ Rejection sent to seller: `{reason}`", ephemeral=True)

        try:
            await self.ticket_channel.send(f"❌ **Your listing submission was declined by staff.**\n📝 **Reason:** {reason}")
        except:
            pass

        try:
            dm_embed = discord.Embed(
                title="❌ YOUR LISTING SUBMISSION WAS DECLINED",
                description=(
                    "Your Call of Duty listing submission has been declined by Pedrao22k staff.\n\n"
                    f"**Reason Provided:**\n> {reason}\n\n"
                    "Please re-check our guidelines and submit clear, unwatermarked proof."
                ),
                color=0xEF4444
            )
            await self.seller.send(embed=dm_embed)
        except:
            pass

# ======================== معرض الماركت مع زر الشراء ========================
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
        price_field = next((f.value for f in self.embed_data.fields if f.name == "💰 Asking Price"), "Check listing")

        buy_embed = discord.Embed(
            title="🛒 ACCOUNT PURCHASE ORDER",
            description=(
                f"Welcome {interaction.user.mention}!\n"
                "You opened this ticket to purchase this verified Call of Duty account:\n\n"
                f"💰 **Price:** `{price_field}`\n\n"
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

# ======================== واجهة الإدارة ========================
class AdminApprovalView(View):
    def __init__(self, seller: discord.User, embed_data: discord.Embed, ticket_channel: discord.TextChannel, images: list):
        super().__init__(timeout=None)
        self.seller = seller
        self.embed_data = embed_data
        self.ticket_channel = ticket_channel
        self.images = images
        self.current_index = 0
        self.posted_market_message = None
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

    @discord.ui.button(label="Approve & Post to Market", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def approve(self, interaction: discord.Interaction, button: Button):
        market_channel = interaction.guild.get_channel(MARKETPLACE_CHANNEL_ID)
        
        self.embed_data.title = "🛒 VERIFIED ACCOUNT LISTING | CALL OF DUTY"
        self.embed_data.color = 0xF59E0B
        self.embed_data.set_footer(text="Pedrao22k. | Verified Listing • Click 'Buy This Account' below to purchase!")

        if market_channel:
            if self.images:
                self.embed_data.set_image(url=self.images[0])
            market_view = MarketplaceCarouselView(images=self.images, embed_data=self.embed_data, is_sold=False)
            self.posted_market_message = await market_channel.send(embed=self.embed_data, view=market_view)
        
        button.disabled = True
        self.reject.disabled = True
        self.sold_btn.disabled = False
        await interaction.response.edit_message(content="✅ **Listing Published to Marketplace! Click 'Mark as SOLD' below when completed.**", view=self)
        
        try:
            await self.ticket_channel.send("🎉 **Congratulations! Staff has verified all details and published your listing in the marketplace!**")
        except:
            pass

        try:
            market_link = self.posted_market_message.jump_url if self.posted_market_message else ""
            dm_embed = discord.Embed(
                title="🎉 YOUR COD ACCOUNT IS NOW LIVE ON MARKETPLACE!",
                description=(
                    "Your listing has been verified and published by Pedrao22k Staff.\n\n"
                    f"🔗 **View your listing:** [Click Here]({market_link})\n\n"
                    "We will notify you immediately once a buyer opens an escrow purchase ticket!"
                ),
                color=0x10B981
            )
            await self.seller.send(embed=dm_embed)
        except:
            pass

    @discord.ui.button(label="Reject Listing", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def reject(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RejectReasonModal(seller=self.seller, ticket_channel=self.ticket_channel))
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content="❌ **Listing was rejected by staff.**", view=self)

    @discord.ui.button(label="Mark as SOLD", style=discord.ButtonStyle.danger, emoji="🏷️", disabled=True, row=1)
    async def sold_btn(self, interaction: discord.Interaction, button: Button):
        if self.posted_market_message:
            sold_embed = self.posted_market_message.embeds[0]
            sold_embed.title = "🔴 [SOLD OUT] ACCOUNT SOLD | CALL OF DUTY"
            sold_embed.color = 0x475569
            sold_embed.set_footer(text="Pedrao22k. | 🔒 This account has been successfully sold.")

            sold_view = MarketplaceCarouselView(images=self.images, embed_data=sold_embed, is_sold=True)
            await self.posted_market_message.edit(embed=sold_embed, view=sold_view)

        button.disabled = True
        await interaction.response.edit_message(content="🔒 **Account marked as SOLD OUT in the marketplace! Buy button is now disabled.**", view=self)
        try:
            await self.ticket_channel.send("🎉 **Your account has been officially marked as SOLD! Thank you for selling with Pedrao22k Services.**")
        except:
            pass

# ======================== زر فتح الرابط في التذكرة ========================
class DirectPortalLauncherView(View):
    def __init__(self, session_id: str):
        super().__init__(timeout=None)
        upload_url = f"{BASE_WEB_URL}/upload?session={session_id}"
        self.add_item(Button(label="Open Seller Portal (WARZONE / MW4)", style=discord.ButtonStyle.link, url=upload_url, emoji="⚡"))

# زر فتح تذكرة البيع وقفل الشات فوراً
class MarketplaceLauncherView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Sell Call of Duty Account", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="sell_cod_account_btn")
    async def open_ticket_direct(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        sell_category = guild.get_channel(SELL_CATEGORY_ID)
        support_role = guild.get_role(SUPPORT_ROLE_ID)

        clean_user_name = interaction.user.name.lower().replace(" ", "-")
        channel_name = f"🏷️・sell-{clean_user_name}"

        existing = discord.utils.get(sell_category.text_channels, name=channel_name)
        if existing:
            return await interaction.followup.send(f"⚠️ You already have an open seller ticket: {existing.mention}", ephemeral=True)

        # قفل الكتابة وإرفاق الملفات على البائع فور إنشاء التذكرة
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=False, attach_files=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)

        sell_ticket_channel = await guild.create_text_channel(name=channel_name, category=sell_category, overwrites=overwrites)

        session_id = str(uuid.uuid4())[:8]

        welcome_embed = discord.Embed(
            title="⚡ CALL OF DUTY | SELLER VERIFICATION PORTAL",
            description=(
                f"Welcome {interaction.user.mention}!\n\n"
                "### 🌐 ALL-IN-ONE SELLER DASHBOARD:\n"
                "Click the button below to open our web interface:\n"
                "> 1️⃣ Fill in your **Asking Price** and **Description**.\n"
                "> 2️⃣ Select or Drag & Drop **all your screenshots** (No limits!).\n"
                "> 3️⃣ Click **Submit** — your listing will be dispatched directly to Staff!\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔒 **Chat is locked:** Submissions are processed exclusively through the web portal.\n"
                "⛔ **STRICT RULE:** It is forbidden for images to contain nicknames or means of communication."
            ),
            color=0xF59E0B
        )
        role_ping = support_role.mention if support_role else ""

        launcher_msg = await sell_ticket_channel.send(content=f"{interaction.user.mention} {role_ping}", embed=welcome_embed, view=DirectPortalLauncherView(session_id=session_id))
        await sell_ticket_channel.send(view=CloseTicketView())
        await interaction.followup.send(f"✅ Your seller room has been created: {sell_ticket_channel.mention}", ephemeral=True)

        active_web_sessions[session_id] = {
            "seller_id": interaction.user.id,
            "channel_id": sell_ticket_channel.id,
            "launcher_msg": launcher_msg,
            "created_at": datetime.datetime.utcnow()
        }

# ======================== صفحة الويب بثيم الشعار الذهبي الكهربائي ========================
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
            --bg-dark: #08080A;
            --card-bg: #121318;
            --border-color: #26241D;
            --input-bg: #1A1A22;
        }
        body {
            background-color: var(--bg-dark);
            color: #F8FAFC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            background-image: radial-gradient(circle at 50% 20%, rgba(245, 158, 11, 0.08) 0%, transparent 60%);
        }
        .container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 32px;
            max-width: 580px;
            width: 100%;
            text-align: left;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.8), 0 0 25px rgba(245, 158, 11, 0.08);
            position: relative;
        }
        .container::before {
            content: '';
            position: absolute;
            top: -1px;
            left: 20%;
            right: 20%;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--gold-primary), transparent);
        }
        h2 { 
            margin-top: 0; 
            color: var(--gold-primary); 
            text-align: center; 
            font-size: 24px;
            letter-spacing: 0.5px;
            text-shadow: 0 0 15px rgba(255, 184, 0, 0.4);
        }
        .subtitle { 
            color: #94A3B8; 
            font-size: 13px; 
            text-align: center; 
            margin-bottom: 24px; 
        }
        label { 
            display: block; 
            font-weight: 600; 
            font-size: 13px; 
            margin-bottom: 6px; 
            color: #E2E8F0; 
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        input[type="text"], textarea {
            width: 100%;
            background: var(--input-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px 14px;
            color: white;
            font-size: 14px;
            box-sizing: border-box;
            margin-bottom: 18px;
            outline: none;
            transition: all 0.25s ease;
        }
        input[type="text"]:focus, textarea:focus { 
            border-color: var(--gold-primary); 
            box-shadow: 0 0 12px rgba(255, 184, 0, 0.25);
        }
        .dropzone {
            border: 2px dashed #3D3522;
            border-radius: 12px;
            padding: 28px 20px;
            cursor: pointer;
            background: #15151C;
            transition: all 0.25s ease;
            text-align: center;
            margin-bottom: 22px;
        }
        .dropzone:hover, .dropzone.dragover { 
            border-color: var(--gold-primary); 
            background: rgba(245, 158, 11, 0.05); 
            box-shadow: inset 0 0 15px rgba(255, 184, 0, 0.1);
        }
        .cloud-icon { 
            font-size: 38px; 
            margin-bottom: 6px; 
            filter: drop-shadow(0 0 8px rgba(255, 184, 0, 0.5));
        }
        .btn {
            background: linear-gradient(135deg, #FFB800 0%, #D97706 100%);
            color: #000;
            padding: 14px 28px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.25s ease;
            width: 100%;
            box-shadow: 0 4px 15px rgba(245, 158, 11, 0.3);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .btn:hover { 
            background: linear-gradient(135deg, #FFC72C 0%, #F59E0B 100%);
            box-shadow: 0 6px 20px rgba(245, 158, 11, 0.5);
            transform: translateY(-1px);
        }
        .btn:disabled { 
            background: #33333D; 
            color: #71717A;
            cursor: not-allowed; 
            box-shadow: none;
            transform: none;
        }
        #status { 
            margin-top: 15px; 
            font-size: 13px; 
            text-align: center; 
            color: #94A3B8; 
        }
        .success { 
            color: #10B981 !important; 
            font-weight: bold; 
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>⚡ CoD Account Submission Portal</h2>
        <div class="subtitle">Enter your account details and upload proof screenshots in one single step.</div>

        <label for="price">Asking Price ($ USD)</label>
        <input type="text" id="price" placeholder="e.g. 150 (Paid in Crypto equivalent)" required>

        <label for="desc">Offer Description</label>
        <textarea id="desc" rows="4" placeholder="Detail your account: mastery camos, levels, rank, skins, CP, access details. No personal contacts." required></textarea>

        <label>Account Screenshots (Unlimited Proofs)</label>
        <div class="dropzone" id="dropArea" onclick="document.getElementById('fileInput').click()">
            <div class="cloud-icon">⚡</div>
            <div id="dropText" style="font-weight: 600; font-size: 15px; color: #F1F5F9;">Click or Drag & Drop Images Here</div>
            <div style="font-size: 12px; color: #94A3B8; margin-top: 6px;">Select all proofs (Lobby, Weapons, Camos, Operators)</div>
        </div>

        <input type="file" id="fileInput" multiple accept="image/*" style="display:none;" onchange="handleFiles(this.files)">
        <button id="submitBtn" class="btn" onclick="submitFullListing()">🚀 Submit Listing to Staff</button>
        <div id="status">Fill details and select screenshots to proceed.</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const session = urlParams.get('session');
        let selectedFiles = [];

        const dropArea = document.getElementById('dropArea');

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.remove('dragover'), false);
        });

        dropArea.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            handleFiles(dt.files);
        }, false);

        function handleFiles(files) {
            for (let i = 0; i < files.length; i++) {
                if (files[i].type.startsWith('image/')) {
                    selectedFiles.push(files[i]);
                }
            }
            document.getElementById('fileInput').value = '';

            if (selectedFiles.length > 0) {
                document.getElementById('dropText').innerText = `✨ ${selectedFiles.length} screenshots selected`;
                document.getElementById('dropText').style.color = '#FFB800';
                document.getElementById('status').innerText = `Ready with ${selectedFiles.length} photo(s). Click or drop more if needed!`;
            }
        }

        async function submitFullListing() {
            const price = document.getElementById('price').value.trim();
            const desc = document.getElementById('desc').value.trim();
            const btn = document.getElementById('submitBtn');
            const status = document.getElementById('status');

            if (!price) { alert("Please specify an asking price."); return; }
            if (!desc) { alert("Please provide an account description."); return; }
            if (selectedFiles.length === 0) { alert("Please attach at least one screenshot."); return; }
            if (!session) { alert("Invalid session. Please reopen from Discord."); return; }

            btn.disabled = true;
            status.innerText = "⏳ Uploading screenshots and sending listing to Staff...";

            const formData = new FormData();
            formData.append("session", session);
            formData.append("price", price);
            formData.append("description", desc);
            selectedFiles.forEach((file) => {
                formData.append("files", file);
            });

            try {
                const res = await fetch("/api/submit_listing", { method: "POST", body: formData });
                const json = await res.json();
                if (json.status === "ok") {
                    status.innerHTML = `<span class="success">🎉 All details and ${json.count} screenshots submitted! You can return to Discord now.</span>`;
                    document.getElementById('dropText').innerText = `✅ Listing Dispatched to Staff`;
                } else {
                    status.innerText = "❌ Submission failed: " + (json.error || "Unknown error");
                    btn.disabled = false;
                }
            } catch (e) {
                status.innerText = "❌ Network error. Please try again.";
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
"""

async def ping_handler(request):
    return web.Response(text="Pedrao22k Bot is Online 24/7!", status=200)

async def handle_web_page(request):
    return web.Response(text=HTML_PAGE, content_type="text/html")

async def handle_api_submit(request):
    reader = await request.multipart()
    session_id = None
    price = ""
    description = ""
    saved_paths = []

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "session":
            session_id = (await part.read()).decode('utf-8')
        elif part.name == "price":
            price = (await part.read()).decode('utf-8')
        elif part.name == "description":
            description = (await part.read()).decode('utf-8')
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
                saved_paths.append(file_path)

    if not session_id or session_id not in active_web_sessions:
        return web.json_response({"status": "error", "error": "Invalid or expired session"}, status=400)

    session_info = active_web_sessions[session_id]
    seller_id = session_info["seller_id"]
    channel_id = session_info["channel_id"]
    launcher_msg = session_info["launcher_msg"]

    ticket_channel = bot.get_channel(channel_id)
    review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
    support_role = ticket_channel.guild.get_role(SUPPORT_ROLE_ID) if ticket_channel else None
    seller = bot.get_user(seller_id) or await bot.fetch_user(seller_id)

    raw_clean_price = price.replace("$", "").replace("USD", "").replace("usd", "").strip()
    formatted_price = f"${raw_clean_price} USD (Paid in Crypto)"

    discord_cdn_urls = []
    batch_size = 10
    for i in range(0, len(saved_paths), batch_size):
        chunk = saved_paths[i:i + batch_size]
        files_to_send = [discord.File(fp) for fp in chunk if os.path.exists(fp)]
        if files_to_send and review_channel:
            batch_msg = await review_channel.send(content=f"📸 *Upload Batch for {seller.mention}:*", files=files_to_send)
            for att in batch_msg.attachments:
                discord_cdn_urls.append(att.url)

    for fp in saved_paths:
        try:
            if os.path.exists(fp):
                os.remove(fp)
        except Exception as e:
            print(f"Error removing temp image: {e}")

    admin_embed = discord.Embed(
        title="📥 NEW VERIFIED COD ACCOUNT SUBMISSION",
        description=f"**Seller:** {seller.mention} (`{seller.id}`)\n**Ticket Channel:** {ticket_channel.mention}",
        color=0xF59E0B,
        timestamp=datetime.datetime.utcnow()
    )
    admin_embed.add_field(name="🎮 Game Title", value="WARZONE / MW4", inline=True)
    admin_embed.add_field(name="💰 Asking Price", value=formatted_price, inline=True)
    admin_embed.add_field(name="📝 Offer Description", value=description[:1024], inline=False)
    admin_embed.add_field(name="📸 Screenshots Received", value=f"`{len(discord_cdn_urls)} photos verified & ready`", inline=False)

    if discord_cdn_urls:
        admin_embed.set_image(url=discord_cdn_urls[0])
    gallery_links = "\n".join([f"• [Image {idx + 1}]({url})" for idx, url in enumerate(discord_cdn_urls[:35])])
    admin_embed.add_field(name="🖼️ Proof Gallery Links", value=gallery_links[:1024], inline=False)

    if review_channel:
        role_ping = support_role.mention if support_role else "@here"
        approval_view = AdminApprovalView(
            seller=seller,
            embed_data=admin_embed,
            ticket_channel=ticket_channel,
            images=discord_cdn_urls
        )
        await review_channel.send(
            content=f"🔔 {role_ping} **New CoD Account Submission! Use buttons below to flip through all {len(discord_cdn_urls)} images:**",
            embed=admin_embed,
            view=approval_view
        )

    submitted_embed = discord.Embed(
        title="✅ LISTING SUBMITTED TO STAFF",
        description=(
            f"**Asking Price:** `{formatted_price}`\n"
            f"**Screenshots:** `{len(discord_cdn_urls)} photos attached`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎉 **Your listing details and all screenshots have been dispatched directly to Staff!**\n"
            "Our verification team is currently inspecting your proofs. You will receive a direct notification once approved."
        ),
        color=0x10B981,
        timestamp=datetime.datetime.utcnow()
    )
    try:
        await launcher_msg.edit(embed=submitted_embed, view=None)
    except Exception as e:
        print(f"Error updating launcher message: {e}")

    active_web_sessions.pop(session_id, None)
    return web.json_response({"status": "ok", "count": len(discord_cdn_urls)})

async def session_cleaner_task():
    while True:
        await asyncio.sleep(300)
        now = datetime.datetime.utcnow()
        expired = [sid for sid, data in active_web_sessions.items() if (now - data["created_at"]).total_seconds() > 1800]
        for sid in expired:
            active_web_sessions.pop(sid, None)

async def start_web_server():
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_get("/", ping_handler)
    app.router.add_get("/upload", handle_web_page)
    app.router.add_post("/api/submit_listing", handle_api_submit)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    print(f"🌐 All-in-One Seller Portal Engine online on 0.0.0.0:{WEB_PORT}!")

# ======================== نظام الفيدباك ========================
class FeedbackModal(Modal, title="Rate Your Experience"):
    def __init__(self):
        super().__init__()
        self.rating_input = TextInput(
            label="Rating (1 to 5 Stars)",
            placeholder="e.g. 5 or ⭐⭐⭐⭐⭐",
            required=True,
            max_length=10
        )
        self.review_input = TextInput(
            label="Your Feedback Review",
            style=discord.TextStyle.paragraph,
            placeholder="How was the service? (Fast delivery, safe escrow, friendly staff...)",
            required=True,
            max_length=500
        )
        self.add_item(self.rating_input)
        self.add_item(self.review_input)

    async def on_submit(self, interaction: discord.Interaction):
        stars = self.rating_input.value.strip()
        comment = self.review_input.value.strip()

        vouch_channel = interaction.guild.get_channel(VOUCH_CHANNEL_ID)
        vouch_embed = discord.Embed(
            title="⭐ NEW VERIFIED CLIENT REVIEW",
            description=f"**Client:** {interaction.user.mention}\n**Rating:** `{stars}`\n\n> {comment}",
            color=0xF59E0B,
            timestamp=datetime.datetime.utcnow()
        )
        vouch_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        vouch_embed.set_footer(text="Pedrao22k Verified Customer Review")

        if vouch_channel:
            await vouch_channel.send(embed=vouch_embed)

        await interaction.response.send_message("🎉 **Thank you so much for your feedback! It has been posted to our vouches channel.**", ephemeral=True)

class FeedbackView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Leave Feedback ⭐", style=discord.ButtonStyle.success, emoji="✍️", custom_id="leave_vouch_btn")
    async def open_feedback_modal(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(FeedbackModal())

@bot.event
async def on_ready():
    bot.add_view(TicketLauncherView())
    bot.add_view(CloseTicketView())
    bot.add_view(MarketplaceLauncherView())
    bot.add_view(FeedbackView())
    bot.add_view(MarketplaceCarouselView(images=[], embed_data=discord.Embed()))
    bot.loop.create_task(start_web_server())
    bot.loop.create_task(session_cleaner_task())
    print(f"Logged in as {bot.user.name} | Railway Cloud Engine Online 24/7!")

@bot.command()
@commands.has_permissions(administrator=True)
async def testwelcome(ctx):
    channel = ctx.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return await ctx.send("❌ Welcome channel not found.")
    embed = build_welcome_embed(ctx.author, ctx.guild)
    await channel.send(content=f"👋 Welcome to the server, {ctx.author.mention}! *(Test Preview)*", embed=embed)
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
            "> **`#⭐︲vouches-feedback`**\n\n"
            "Need anything else? Feel free to ask or click below to close this ticket."
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
            "Welcome to **Pedrao22k Services**. We provide fast, reliable, and completely private gaming solutions handled by top-tier competitive pros.\n\n"
            "### 👑 Available Departments:\n"
            "> 🏆 **Ranked Boosting** — Top 250, Iridescent, Duo Queue, Wins\n"
            "> 🎨 **Camo Services** — Mastery Camos, Weapon Leveling, Challenges\n"
            "> 🛒 **Marketplace** — Buy verified & secure gaming accounts\n"
            "> 💬 **General Support** — Questions, custom requests, & consultations\n\n"
            "--- \n"
            "### 💳 Payment Methods:\n"
            "`USDT (TRC20 / BEP20)` • `Bitcoin (BTC)` • `Litecoin (LTC)`\n\n"
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
            "2. Fill in your account description & price in a single popup window.\n"
            "3. Upload all your screenshots directly.\n"
            "4. Staff will review and verify before publishing to the marketplace.\n\n"
            "Click below to get started!"
        ),
        color=0xF59E0B
    )
    if ctx.guild.icon:
        embed.set_author(name="Pedrao22k Marketplace", icon_url=ctx.guild.icon.url)
    embed.set_footer(text="Pedrao22k. | Verified Seller Hub")
    await ctx.send(embed=embed, view=MarketplaceLauncherView())

bot.run(TOKEN)
