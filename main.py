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

# إعدادات واجهة الويب على Railway (مطابقة للمنفذ والرابط الخاص بك)
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
    def __init__(self, seller: discord.User, ticket_channel: discord.TextChannel, launcher_msg: discord.Message = None, price_str: str = "", count_str: str = ""):
        super().__init__()
        self.seller = seller
        self.ticket_channel = ticket_channel
        self.launcher_msg = launcher_msg
        self.price_str = price_str
        self.count_str = count_str
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

        if self.launcher_msg:
            try:
                rejected_embed = discord.Embed(
                    title="❌ LISTING SUBMISSION DECLINED BY STAFF",
                    description=(
                        f"Hello {self.seller.mention}, your submitted Call of Duty account listing has been inspected and **declined** by moderation.\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "### 📋 SUBMISSION DETAILS:\n"
                        f"> 💰 **Asking Price:** `{self.price_str}`\n"
                        f"> 📸 **Screenshots:** `{self.count_str}`\n"
                        "> ❌ **Current Status:** `Rejected / Action Required`\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "### 📝 REASON FOR REJECTION:\n"
                        f"> ⚠️ **`{reason}`**\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🛠️ **WHAT YOU CAN DO:**\n"
                        "• Please re-read our safety rules (strictly no gamer tags, nicknames, or watermarks).\n"
                        "• Contact staff in this ticket if you have any questions or want to submit new valid proofs."
                    ),
                    color=0xEF4444,
                    timestamp=datetime.datetime.utcnow()
                )
                if self.seller.display_avatar:
                    rejected_embed.set_thumbnail(url=self.seller.display_avatar.url)
                rejected_embed.set_footer(text="Pedrao22k Services • Moderation Decision")
                await self.launcher_msg.edit(embed=rejected_embed, view=None)
            except Exception as e:
                print(f"Error editing launcher to rejected: {e}")

        try:
            await self.ticket_channel.send(f"⚠️ {self.seller.mention} **Your listing was declined.** Reason: `{reason}`")
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
    def __init__(self, seller: discord.User, embed_data: discord.Embed, ticket_channel: discord.TextChannel, images: list, launcher_msg: discord.Message = None, price_str: str = "", count_str: str = ""):
        super().__init__(timeout=None)
        self.seller = seller
        self.embed_data = embed_data
        self.ticket_channel = ticket_channel
        self.images = images
        self.launcher_msg = launcher_msg
        self.price_str = price_str
        self.count_str = count_str
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
        
        market_link = self.posted_market_message.jump_url if self.posted_market_message else "#accounts-for-sale"

        if self.launcher_msg:
            try:
                approved_embed = discord.Embed(
                    title="🎉 LISTING APPROVED & PUBLISHED ON MARKETPLACE",
                    description=(
                        f"Great news {self.seller.mention}! Your Call of Duty account listing has been verified and **officially published** to our marketplace.\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "### 📋 LISTING DETAILS:\n"
                        f"> 💰 **Asking Price:** `{self.price_str}`\n"
                        f"> 📸 **Screenshots:** `{self.count_str}`\n"
                        "> ✅ **Current Status:** `Live in Marketplace`\n"
                        f"> 🔗 **Listing URL:** [Click to View on Market]({market_link})\n\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "### 🛡️ NEXT ESCROW STEPS:\n"
                        "1️⃣ Your account is now visible to all buyers in <#1552628139618734170>.\n"
                        "2️⃣ When a buyer opens a purchase order, an admin will ping you right here.\n"
                        "3️⃣ Never transfer credentials outside of this ticket under any circumstances."
                    ),
                    color=0x10B981,
                    timestamp=datetime.datetime.utcnow()
                )
                if self.seller.display_avatar:
                    approved_embed.set_thumbnail(url=self.seller.display_avatar.url)
                approved_embed.set_footer(text="Pedrao22k Services • Listing Live")
                await self.launcher_msg.edit(embed=approved_embed, view=None)
            except Exception as e:
                print(f"Error editing launcher to approved: {e}")

        try:
            await self.ticket_channel.send(f"🎉 {self.seller.mention} **Your listing is now live!** Check it here: {market_link}")
        except:
            pass

        try:
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
        modal = RejectReasonModal(
            seller=self.seller,
            ticket_channel=self.ticket_channel,
            launcher_msg=self.launcher_msg,
            price_str=self.price_str,
            count_str=self.count_str
        )
        await interaction.response.send_modal(modal)
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
            "created_at": datetime.datetime.utcnow(),
            "uploaded_files": []
        }

# ======================== صفحة الويب ========================
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
            background-color: var(--bg-dark);
            color: #F8FAFC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 24px 16px;
            position: relative;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 50% 50%, rgba(245, 158, 11, 0.15) 0%, transparent 60%),
                radial-gradient(circle at 20% 20%, rgba(255, 184, 0, 0.1) 0%, transparent 45%),
                radial-gradient(circle at 80% 80%, rgba(217, 119, 6, 0.1) 0%, transparent 45%);
        }
        body::before {
            content: '';
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 650px;
            height: 650px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(255, 184, 0, 0.18) 0%, rgba(245, 158, 11, 0.08) 50%, transparent 75%);
            filter: blur(55px);
            pointer-events: none;
            z-index: 0;
        }
        .container {
            background: var(--card-bg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 34px 28px;
            max-width: 580px;
            width: 100%;
            text-align: left;
            box-shadow: 
                0 25px 50px rgba(0, 0, 0, 0.95),
                0 0 45px rgba(245, 158, 11, 0.2),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
            position: relative;
            z-index: 1;
            transition: all 0.4s ease;
        }
        .container::before {
            content: '';
            position: absolute;
            top: -1px;
            left: 15%;
            right: 15%;
            height: 2px;
            background: linear-gradient(90deg, transparent, #FFB800, #F59E0B, transparent);
            box-shadow: 0 0 18px #FFB800;
        }
        .header-logo {
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 12px;
        }
        .header-logo .lightning {
            font-size: 38px;
            color: var(--gold-primary);
            filter: drop-shadow(0 0 15px rgba(255, 184, 0, 0.9));
            animation: pulse-glow 2s infinite alternate ease-in-out;
        }
        @keyframes pulse-glow {
            0% { transform: scale(1); filter: drop-shadow(0 0 10px rgba(255, 184, 0, 0.7)); }
            100% { transform: scale(1.12); filter: drop-shadow(0 0 25px rgba(255, 184, 0, 1)); }
        }
        h2 { 
            margin: 0; 
            color: #FFFFFF; 
            text-align: center; 
            font-size: 24px;
            font-weight: 800;
            letter-spacing: 0.6px;
            text-shadow: 0 2px 10px rgba(0,0,0,0.7);
        }
        h2 span {
            color: var(--gold-primary);
            text-shadow: 0 0 20px rgba(255, 184, 0, 0.7);
        }
        .subtitle { 
            color: #94A3B8; 
            font-size: 13px; 
            text-align: center; 
            margin-top: 6px;
            margin-bottom: 26px; 
            line-height: 1.5;
        }
        label { 
            display: block; 
            font-weight: 700; 
            font-size: 12px; 
            margin-bottom: 7px; 
            color: #E2E8F0; 
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }
        input[type="text"], textarea {
            width: 100%;
            background: var(--input-bg);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 13px 15px;
            color: #FFFFFF;
            font-size: 14px;
            margin-bottom: 18px;
            outline: none;
            transition: all 0.25s ease;
        }
        input[type="text"]:focus, textarea:focus { 
            border-color: var(--gold-primary); 
            background: rgba(26, 27, 36, 0.95);
            box-shadow: 0 0 16px rgba(255, 184, 0, 0.35);
        }
        .dropzone {
            border: 2px dashed rgba(245, 158, 11, 0.45);
            border-radius: 14px;
            padding: 26px 18px;
            cursor: pointer;
            background: rgba(18, 19, 26, 0.65);
            transition: all 0.25s ease;
            text-align: center;
            margin-bottom: 16px;
        }
        .dropzone:hover, .dropzone.dragover { 
            border-color: var(--gold-primary); 
            background: rgba(245, 158, 11, 0.1); 
            box-shadow: 0 0 25px rgba(255, 184, 0, 0.25), inset 0 0 15px rgba(255, 184, 0, 0.15);
        }
        .cloud-icon { 
            font-size: 36px; 
            margin-bottom: 6px; 
            color: var(--gold-primary);
            filter: drop-shadow(0 0 12px rgba(255, 184, 0, 0.8));
        }

        .progress-box {
            display: none;
            margin-bottom: 20px;
        }
        .progress-header {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 6px;
            color: #CBD5E1;
        }
        .progress-bar-bg {
            width: 100%;
            height: 10px;
            background: #232530;
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.06);
            position: relative;
        }
        .progress-bar-fill {
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, #D97706, #FFB800);
            border-radius: 6px;
            transition: width 0.25s ease;
            box-shadow: 0 0 12px rgba(255, 184, 0, 0.6);
        }

        .progress-bar-fill.reloading {
            width: 100% !important;
            background: linear-gradient(90deg, #D97706, #FFB800, #F59E0B, #D97706);
            background-size: 200% 100%;
            animation: bar-reload 1.2s infinite linear;
            box-shadow: 0 0 18px rgba(255, 184, 0, 0.85);
        }
        @keyframes bar-reload {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }

        .btn {
            background: #252631;
            color: #64748B;
            padding: 15px 28px;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 800;
            cursor: not-allowed;
            transition: all 0.3s ease;
            width: 100%;
            box-shadow: none;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn.ready {
            background: linear-gradient(135deg, #FFB800 0%, #D97706 100%);
            color: #050507;
            cursor: pointer;
            box-shadow: 0 4px 25px rgba(245, 158, 11, 0.45);
        }
        .btn.ready:hover { 
            background: linear-gradient(135deg, #FFC72C 0%, #F59E0B 100%);
            box-shadow: 0 6px 30px rgba(255, 184, 0, 0.7);
            transform: translateY(-2px);
        }

        .success-screen {
            display: none;
            text-align: center;
            padding: 10px 4px;
            animation: fadeIn 0.4s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .success-icon {
            font-size: 60px;
            margin-bottom: 12px;
            filter: drop-shadow(0 0 20px rgba(16, 185, 129, 0.8));
            animation: pulse-glow-success 2s infinite alternate ease-in-out;
        }
        @keyframes pulse-glow-success {
            0% { transform: scale(1); }
            100% { transform: scale(1.1); }
        }
        .success-title {
            color: #10B981;
            font-size: 22px;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-bottom: 12px;
            text-shadow: 0 0 15px rgba(16, 185, 129, 0.4);
        }
        .success-desc {
            color: #E2E8F0;
            font-size: 15px;
            line-height: 1.6;
            margin-bottom: 24px;
            background: rgba(22, 23, 31, 0.7);
            border: 1px solid rgba(245, 158, 11, 0.25);
            border-radius: 12px;
            padding: 18px 16px;
        }
        .success-desc strong {
            color: #FFB800;
        }
        .discord-btn {
            background: linear-gradient(135deg, #5865F2 0%, #4752C4 100%);
            color: #FFFFFF;
            padding: 14px 28px;
            border-radius: 10px;
            font-weight: 800;
            text-transform: uppercase;
            text-decoration: none;
            display: inline-block;
            box-shadow: 0 4px 20px rgba(88, 101, 242, 0.4);
            transition: all 0.25s ease;
            letter-spacing: 0.6px;
        }
        .discord-btn:hover {
            box-shadow: 0 6px 28px rgba(88, 101, 242, 0.7);
            transform: translateY(-2px);
        }

        #status { 
            margin-top: 15px; 
            font-size: 13px; 
            text-align: center; 
            color: #94A3B8; 
            line-height: 1.4;
        }
        .notice-wait {
            color: #FFB800 !important;
            font-weight: 700;
            font-size: 13px;
        }
        .error-msg {
            color: #EF4444 !important;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container" id="mainContainer">
        <!-- شاشة نموذج الإدخال -->
        <div id="formScreen">
            <div class="header-logo">
                <span class="lightning">⚡</span>
            </div>
            <h2>PEDRAO22K <span>SELLER PORTAL</span></h2>
            <div class="subtitle">Submit your account listing & upload unlimited proof screenshots in one click.</div>

            <label for="price">Asking Price ($ USD)</label>
            <input type="text" id="price" inputmode="numeric" placeholder="e.g. 150 (Numbers only)" oninput="filterNumbersOnly(this)" required>

            <label for="desc">Offer Description</label>
            <textarea id="desc" rows="4" placeholder="Detail your account: mastery camos, levels, rank, skins, CP, access details. No personal contacts." required></textarea>

            <label>Account Screenshots (Unlimited Proofs)</label>
            <div class="dropzone" id="dropArea" onclick="document.getElementById('fileInput').click()">
                <div class="cloud-icon">⚡</div>
                <div id="dropText" style="font-weight: 700; font-size: 15px; color: #FFFFFF;">Click or Drag & Drop Images Here</div>
                <div id="dropSub" style="font-size: 12px; color: #94A3B8; margin-top: 6px;">Select all proofs (Lobby, Weapons, Camos, Operators)</div>
            </div>

            <div class="progress-box" id="progressBox">
                <div class="progress-header">
                    <span id="progressText">Uploading Screenshots...</span>
                    <span id="progressPercent" style="color: #FFB800;">0%</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="progressBarFill"></div>
                </div>
            </div>

            <input type="file" id="fileInput" multiple accept="image/*" style="display:none;" onchange="handleFileSelection(this.files)">
            <button id="submitBtn" class="btn" disabled onclick="submitFinalListing()">🚀 Submit Listing to Staff</button>
            <div id="status">Select screenshots to begin instant upload.</div>
        </div>

        <!-- شاشة النجاح والتأكيد المحدثة بالنص المطلوب حرفياً -->
        <div class="success-screen" id="successScreen">
            <div class="success-icon">🎉</div>
            <div class="success-title">YOUR OFFER IS UNDER REVIEW!</div>
            <div class="success-desc">
                Your account details, including the full description and all screenshots, have been safely received.<br><br>
                <strong>👉 Please wait for the admin to approve your offer.</strong><br>
                No further action is required from you here. We will notify you inside your Discord ticket once reviewed!
            </div>
            <a href="https://discord.com/channels/@me" class="discord-btn" onclick="window.close()">Return to Discord</a>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const session = urlParams.get('session');
        let isUploaded = false;
        let uploadedCount = 0;

        const dropArea = document.getElementById('dropArea');
        const progressBox = document.getElementById('progressBox');
        const progressBarFill = document.getElementById('progressBarFill');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');
        const submitBtn = document.getElementById('submitBtn');
        const status = document.getElementById('status');

        function filterNumbersOnly(input) {
            input.value = input.value.replace(/[^0-9]/g, '');
        }

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
            document.body.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.remove('dragover'), false);
        });

        dropArea.addEventListener('drop', (e) => {
            handleFileSelection(e.dataTransfer.files);
        }, false);

        function handleFileSelection(files) {
            let validFiles = [];
            for (let i = 0; i < files.length; i++) {
                if (files[i].type.startsWith('image/')) {
                    validFiles.push(files[i]);
                }
            }
            if (validFiles.length === 0) return;

            uploadImagesDirectly(validFiles);
        }

        function uploadImagesDirectly(files) {
            if (!session) {
                alert("Invalid or missing session. Please open the link again from Discord.");
                return;
            }

            isUploaded = false;
            submitBtn.disabled = true;
            submitBtn.classList.remove('ready');
            submitBtn.innerText = "⏳ Uploading Screenshots...";

            progressBox.style.display = "block";
            progressBarFill.classList.remove('reloading');
            progressBarFill.style.width = "0%";
            progressText.innerText = `Uploading ${files.length} screenshots...`;
            progressPercent.innerText = "0%";
            status.innerText = "Uploading screenshots to server...";

            const formData = new FormData();
            formData.append("session", session);
            for (let i = 0; i < files.length; i++) {
                formData.append("files", files[i]);
            }

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
                        uploadedCount = res.total_uploaded;
                        progressBarFill.style.width = "100%";
                        progressPercent.innerText = "100%";
                        progressText.innerText = "✅ Screenshots Ready!";
                        
                        document.getElementById('dropText').innerText = `✨ ${uploadedCount} Screenshots Ready`;
                        document.getElementById('dropText').style.color = '#FFB800';
                        document.getElementById('dropSub').innerText = "All photos loaded. Fill details and click submit below.";

                        isUploaded = true;
                        submitBtn.disabled = false;
                        submitBtn.classList.add('ready');
                        submitBtn.innerText = "🚀 Submit Listing to Staff";
                        status.innerHTML = `<span class="notice-wait">✨ ${uploadedCount} photo(s) ready! Click submit to dispatch.</span>`;
                    } else {
                        status.innerHTML = `<span class="error-msg">❌ Error: ${res.error || "Session expired. Please reopen from Discord."}</span>`;
                        submitBtn.innerText = "❌ Upload Failed";
                    }
                } catch (e) {
                    status.innerHTML = `<span class="error-msg">❌ Server response error. Please reopen link from Discord ticket.</span>`;
                }
            };

            xhr.onerror = function() {
                status.innerHTML = `<span class="error-msg">❌ Network connection error. Please try again.</span>`;
            };

            xhr.send(formData);
        }

        async function submitFinalListing() {
            const price = document.getElementById('price').value.trim();
            const desc = document.getElementById('desc').value.trim();

            if (!price || isNaN(price) || parseInt(price) <= 0) { 
                alert("Please enter a valid numeric asking price (numbers only)."); 
                document.getElementById('price').focus();
                return; 
            }
            if (!desc) { alert("Please provide an account description."); return; }
            if (!isUploaded || uploadedCount === 0) { alert("Please wait for screenshots to finish uploading."); return; }

            submitBtn.disabled = true;
            submitBtn.classList.remove('ready');
            submitBtn.innerText = "⏳ Processing...";

            progressBox.style.display = "block";
            progressBarFill.classList.add('reloading');
            progressText.innerText = "⚡ Dispatched to Discord Staff...";
            progressPercent.innerText = "Processing...";

            status.innerHTML = `<span class="notice-wait">⏳ Please wait, we are completing the process, do not do anything...</span>`;

            const formData = new FormData();
            formData.append("session", session);
            formData.append("price", price);
            formData.append("description", desc);

            try {
                const res = await fetch("/api/finalize_listing", { method: "POST", body: formData });
                const json = await res.json();
                if (json.status === "ok") {
                    document.getElementById('formScreen').style.display = 'none';
                    document.getElementById('successScreen').style.display = 'block';
                } else {
                    progressBarFill.classList.remove('reloading');
                    status.innerHTML = `<span class="error-msg">❌ Failed: ${json.error || "Unknown error"}</span>`;
                    submitBtn.disabled = false;
                    submitBtn.classList.add('ready');
                    submitBtn.innerText = "🚀 Submit Listing to Staff";
                }
            } catch (e) {
                progressBarFill.classList.remove('reloading');
                status.innerHTML = `<span class="error-msg">❌ Network error. Please try again.</span>`;
                submitBtn.disabled = false;
                submitBtn.classList.add('ready');
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
    return web.Response(text=HTML_PAGE, content_type="text/html")

async def handle_upload_images_only(request):
    try:
        reader = await request.multipart()
        session_id = None
        saved_paths = []

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "session":
                session_id = (await part.read()).decode('utf-8')
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

        if not session_id:
            return web.json_response({"status": "error", "error": "Missing session ID"}, status=400)

        if session_id not in active_web_sessions:
            return web.json_response({"status": "error", "error": "Session expired or bot restarted. Please click the button in your Discord ticket again!"}, status=400)

        active_web_sessions[session_id]["uploaded_files"].extend(saved_paths)
        total_files = len(active_web_sessions[session_id]["uploaded_files"])
        return web.json_response({"status": "ok", "total_uploaded": total_files})
    except Exception as e:
        print(f"Upload error: {e}")
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def handle_finalize_listing(request):
    try:
        data = await request.post()
        session_id = data.get("session")
        price = data.get("price", "")
        description = data.get("description", "")

        if not session_id or session_id not in active_web_sessions:
            return web.json_response({"status": "error", "error": "Session expired. Reopen from Discord."}, status=400)

        session_info = active_web_sessions[session_id]
        saved_paths = session_info.get("uploaded_files", [])
        seller_id = session_info["seller_id"]
        channel_id = session_info["channel_id"]
        launcher_msg = session_info["launcher_msg"]

        ticket_channel = bot.get_channel(channel_id)
        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        support_role = ticket_channel.guild.get_role(SUPPORT_ROLE_ID) if ticket_channel else None
        seller = bot.get_user(seller_id) or await bot.fetch_user(seller_id)

        raw_clean_price = price.replace("$", "").replace("USD", "").replace("usd", "").strip()
        formatted_price = f"${raw_clean_price} USD (Paid in Crypto)"
        count_str = f"{len(saved_paths)} proofs attached"

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

        # بطاقة تأكيد أنيقة في تذكرة البائع أثناء انتظار الإدارة
        submitted_embed = discord.Embed(
            title="🚀 OFFER SUCCESSFULLY SUBMITTED TO STAFF",
            description=(
                f"Thank you {seller.mention}! Your Call of Duty account listing has been securely recorded and dispatched to our moderation queue.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "### 📋 SUBMISSION OVERVIEW:\n"
                f"> 💰 **Asking Price:** `{formatted_price}`\n"
                f"> 📸 **Screenshots Verified:** `{len(discord_cdn_urls)} proofs uploaded`\n"
                "> ⏳ **Current Status:** `Pending Admin Verification`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "### 📌 WHAT HAPPENS NEXT?\n"
                "1️⃣ **Inspection:** Staff is inspecting all screenshots for compliance with safety rules.\n"
                "2️⃣ **Marketplace Release:** Once approved, your listing will be published directly to <#1552628139618734170>.\n"
                "3️⃣ **Direct Alert:** You will receive a direct notification the second a buyer opens an escrow deal.\n\n"
                "⚠️ **IMPORTANT NOTICE:**\n"
                "**PLEASE WAIT PATIENTLY FOR THE ADMIN TO APPROVE YOUR OFFER!**\n"
                "This card will automatically update once staff makes a decision."
            ),
            color=0xF59E0B,
            timestamp=datetime.datetime.utcnow()
        )
        if seller.display_avatar:
            submitted_embed.set_thumbnail(url=seller.display_avatar.url)
        submitted_embed.set_footer(text="Pedrao22k Services • Awaiting Review")

        try:
            await launcher_msg.edit(embed=submitted_embed, view=None)
            await ticket_channel.send(f"🔔 {seller.mention} **Your offer was submitted! Please wait for staff review.** ⏳")
        except Exception as e:
            print(f"Error updating launcher message: {e}")

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
                images=discord_cdn_urls,
                launcher_msg=launcher_msg,
                price_str=formatted_price,
                count_str=f"{len(discord_cdn_urls)} proofs"
            )
            await review_channel.send(
                content=f"🔔 {role_ping} **New CoD Account Submission! Use buttons below to flip through all {len(discord_cdn_urls)} images:**",
                embed=admin_embed,
                view=approval_view
            )

        active_web_sessions.pop(session_id, None)
        return web.json_response({"status": "ok", "count": len(discord_cdn_urls)})
    except Exception as e:
        print(f"Finalize error: {e}")
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def session_cleaner_task():
    while True:
        await asyncio.sleep(300)
        now = datetime.datetime.utcnow()
        expired = [sid for sid, data in active_web_sessions.items() if (now - data["created_at"]).total_seconds() > 3600]
        for sid in expired:
            active_web_sessions.pop(sid, None)

async def start_web_server():
    app = web.Application(client_max_size=300 * 1024 * 1024)
    app.router.add_get("/", ping_handler)
    app.router.add_get("/upload", handle_web_page)
    app.router.add_post("/api/upload_images_only", handle_upload_images_only)
    app.router.add_post("/api/finalize_listing", handle_finalize_listing)
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
