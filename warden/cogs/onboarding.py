"""Join role, welcome message + DM, and a rules button that verifies members.

Runs on ``warden_member_admitted``, which automod dispatches for joins that
aren't blocked by raid mode.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..actions import render
from ..settings import SettingType, setting_group

if TYPE_CHECKING:
    from ..bot import Warden

log = logging.getLogger(__name__)


_define = setting_group("onboarding")

JOIN_ROLE = _define("join_role", SettingType.ROLE, None, "Role given to everyone who joins.")
WELCOME_CHANNEL = _define("welcome_channel", SettingType.CHANNEL, None, "Channel for welcome messages.")
WELCOME_MESSAGE = _define(
    "welcome_message",
    SettingType.STRING,
    "Welcome to **{server}**, {mention}! You're member #{count}.",
    "Welcome text in the channel. Placeholders: {mention} {user} {server} {count}. Use \\n for a new line.",
)
DM_ENABLED = _define(
    "dm_enabled",
    SettingType.BOOL,
    True,
    "Also DM new members. If their DMs are closed, the DM text is added to the channel message.",
)
DM_MESSAGE = _define(
    "dm_message",
    SettingType.STRING,
    "Hi {user}, welcome to **{server}**! Read the rules and press **I agree** to get access.",
    "Text of the welcome DM. Same placeholders.",
)
VERIFIED_ROLE = _define(
    "verified_role", SettingType.ROLE, None, "Role given when a member presses I agree on the rules."
)

VERIFY_ID = "warden:verify"


class VerifyView(discord.ui.View):
    """Persistent: the button keeps working after restarts because its custom_id is fixed."""

    def __init__(self, bot: Warden) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="I agree", style=discord.ButtonStyle.success, emoji="✅", custom_id=VERIFY_ID)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        guild = interaction.guild
        member = interaction.user
        role_id = await self.bot.settings.get(guild.id, VERIFIED_ROLE)
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message(
                "Verification isn't set up yet. Please tell a moderator.", ephemeral=True
            )
            return
        if member.get_role(role.id):
            await interaction.response.send_message("You're already verified.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="Accepted the rules")
        except discord.HTTPException:
            log.warning("Couldn't give verified role %s in %s", role.id, guild.id)
            await interaction.response.send_message(
                "I couldn't give you the role. Please tell a moderator.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Thanks! You now have {role.mention}. Enjoy the server.", ephemeral=True
        )


class RulesModal(discord.ui.Modal, title="Post the rules"):
    heading = discord.ui.TextInput(label="Title", default="Server rules", max_length=256)
    body = discord.ui.TextInput(
        label="Rules",
        style=discord.TextStyle.paragraph,
        placeholder="1. Be respectful\n2. No spam\n3. ...",
        max_length=4000,
    )

    def __init__(self, bot: Warden, channel: discord.TextChannel) -> None:
        super().__init__()
        self.bot = bot
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=self.heading.value, description=self.body.value, colour=discord.Colour.blurple()
        )
        embed.set_footer(text="Press I agree to confirm you've read the rules.")
        try:
            await self.channel.send(embed=embed, view=VerifyView(self.bot))
        except discord.HTTPException:
            await interaction.response.send_message(
                f"I couldn't post in {self.channel.mention}.", ephemeral=True
            )
            return
        note = ""
        if await self.bot.settings.get(interaction.guild_id, VERIFIED_ROLE) is None:
            note = "\n:warning: Set the role the button gives: `/config set key:onboarding.verified_role value:@Role`"
        await interaction.response.send_message(
            f"Rules posted in {self.channel.mention}.{note}", ephemeral=True
        )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Onboarding(commands.GroupCog, group_name="onboarding", group_description="Welcome and verification"):
    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        self.settings = bot.settings
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_view(VerifyView(self.bot))

    async def welcome(self, member: discord.Member) -> list[str]:
        """Run the join flow for ``member``. Returns notes on anything that failed."""
        guild = member.guild
        problems: list[str] = []

        role_id = await self.settings.get(guild.id, JOIN_ROLE)
        role = guild.get_role(role_id) if role_id else None
        if role is not None and not member.get_role(role.id):
            try:
                await member.add_roles(role, reason="Join role")
            except discord.HTTPException:
                problems.append(f"couldn't give {role.mention} (is it above my role?)")

        dm_text = render(await self.settings.get(guild.id, DM_MESSAGE), member)
        wants_dm = await self.settings.get(guild.id, DM_ENABLED) and not member.bot
        dm_sent = False
        if wants_dm:
            try:
                await member.send(dm_text)
                dm_sent = True
            except discord.HTTPException:
                problems.append("their DMs are closed, so the DM text went to the channel")

        channel_id = await self.settings.get(guild.id, WELCOME_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.abc.Messageable):
            text = render(await self.settings.get(guild.id, WELCOME_MESSAGE), member)
            if wants_dm and not dm_sent:
                text += "\n" + dm_text
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.HTTPException:
                problems.append(f"couldn't post in {channel.mention}")
        elif channel_id:
            problems.append("the welcome channel no longer exists")
        return problems

    @commands.Cog.listener()
    async def on_warden_member_admitted(self, member: discord.Member) -> None:
        for problem in await self.welcome(member):
            log.info("Welcome for %s in %s: %s", member.id, member.guild.id, problem)

    @app_commands.command(name="rules", description="Post the rules with an I agree button")
    @app_commands.describe(channel="Where to post them")
    async def rules(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                f"I need Send Messages and Embed Links in {channel.mention}.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RulesModal(self.bot, channel))

    @app_commands.command(name="test", description="Run the welcome flow on yourself to preview it")
    async def test(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        problems = await self.welcome(interaction.user)
        summary = "Welcome flow ran. Check the welcome channel and your DMs."
        if problems:
            summary += "\n" + "\n".join(f"- {p}" for p in problems)
        await interaction.followup.send(summary, ephemeral=True)


async def setup(bot: Warden) -> None:
    await bot.add_cog(Onboarding(bot))
