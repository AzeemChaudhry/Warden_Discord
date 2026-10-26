"""Roles unlocked at levels: colour roles, image permissions, private channels.

A perk is just a role. Whatever the role grants (a colour, Attach Files, access
to a hidden channel) is set up in Discord; this module hands it out.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..levels import level_for, reward_roles_for
from ..settings import Setting, SettingType, register

if TYPE_CHECKING:
    from ..bot import Warden

log = logging.getLogger(__name__)

STACK = register(
    Setting(
        key="perks.stack",
        type=SettingType.BOOL,
        default=True,
        description="Keep lower-level reward roles after earning a higher one.",
    )
)


def assign_error(role: discord.Role) -> str | None:
    """Why the bot can't hand out ``role``, or None if it can."""
    me = role.guild.me
    if role.is_default():
        return "@everyone can't be a reward."
    if role.managed:
        return f"{role.mention} is managed by an integration and can't be assigned."
    if not me.guild_permissions.manage_roles:
        return "I need the Manage Roles permission."
    if role >= me.top_role:
        return f"{role.mention} is above my highest role. Move my role above it in Server Settings → Roles."
    return None


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class Perks(commands.GroupCog, group_name="perks", group_description="Roles members unlock by levelling up"):
    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        super().__init__()

    async def sync_member(
        self, member: discord.Member, level: int
    ) -> tuple[list[discord.Role], list[discord.Role]]:
        """Give and remove reward roles so they match ``level``. Returns (added, removed)."""
        guild = member.guild
        rewards = await self.bot.levels.rewards(guild.id)
        if not rewards:
            return [], []
        stack = await self.bot.settings.get(guild.id, STACK)
        wanted = reward_roles_for(level, rewards, stack)
        reward_ids = {role_id for _, role_id in rewards}
        held = {r.id for r in member.roles}

        def usable(ids: set[int]) -> list[discord.Role]:
            roles = [guild.get_role(i) for i in ids]
            return [r for r in roles if r is not None and assign_error(r) is None]

        to_add = usable(wanted - held)
        to_remove = usable((reward_ids - wanted) & held)
        try:
            if to_add:
                await member.add_roles(*to_add, reason=f"Level {level} reward")
            if to_remove:
                await member.remove_roles(*to_remove, reason=f"Level {level}: reward no longer applies")
        except discord.HTTPException:
            log.warning("Couldn't sync perks for %s in %s", member.id, guild.id, exc_info=True)
            return [], []
        return to_add, to_remove

    @commands.Cog.listener()
    async def on_warden_level_changed(self, member: discord.Member, old_level: int, new_level: int) -> None:
        await self.sync_member(member, new_level)

    @app_commands.command(name="add", description="Unlock a role at a level")
    @app_commands.describe(level="Level that unlocks it", role="Role to give")
    async def add(
        self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500], role: discord.Role
    ) -> None:
        if error := assign_error(role):
            await interaction.response.send_message(error, ephemeral=True)
            return
        await self.bot.levels.add_reward(interaction.guild_id, level, role.id)
        await interaction.response.send_message(
            f"Members reaching **level {level}** now get {role.mention}. "
            "Run `/perks sync` to give it to people already past that level.",
            ephemeral=True,
        )

    @app_commands.command(name="remove", description="Stop giving a role at a level")
    @app_commands.describe(level="The level it's unlocked at", role="The role")
    async def remove(
        self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 500], role: discord.Role
    ) -> None:
        removed = await self.bot.levels.remove_reward(interaction.guild_id, level, role.id)
        message = (
            f"{role.mention} is no longer a level {level} reward. Members who have it keep it."
            if removed
            else f"{role.mention} isn't a level {level} reward."
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="list", description="Show every level reward")
    async def list_(self, interaction: discord.Interaction) -> None:
        rewards = await self.bot.levels.rewards(interaction.guild_id)
        if not rewards:
            await interaction.response.send_message(
                "No level rewards yet. Add one with `/perks add`.", ephemeral=True
            )
            return
        stack = await self.bot.settings.get(interaction.guild_id, STACK)
        lines = []
        for level, role_id in rewards:
            role = interaction.guild.get_role(role_id)
            problem = assign_error(role) if role else "role was deleted"
            lines.append(f"**Level {level}** · <@&{role_id}>" + (f"  :warning: {problem}" if problem else ""))
        embed = discord.Embed(
            title="Level rewards", description="\n".join(lines), colour=discord.Colour.purple()
        )
        embed.set_footer(text="Lower rewards are kept" if stack else "Only the highest reward is kept")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sync", description="Re-apply level rewards for a member, or everyone with XP")
    @app_commands.describe(member="Leave empty to sync everyone with XP")
    async def sync(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if member is not None:
            targets = [member]
        else:
            ids = [uid for uid, _ in await self.bot.levels.top(guild.id, limit=10_000)]
            targets = [m for m in (guild.get_member(i) for i in ids) if m is not None]

        changed = 0
        for target in targets:
            level = level_for(await self.bot.levels.get_xp(guild.id, target.id))
            added, removed = await self.sync_member(target, level)
            changed += bool(added or removed)
        await interaction.followup.send(
            f"Checked {len(targets)} member(s); updated {changed}.", ephemeral=True
        )


async def setup(bot: Warden) -> None:
    await bot.add_cog(Perks(bot))
