import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Optional, Union
import logging
from collections import defaultdict
import os

class ModBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.warning_counts = defaultdict(int)
        self.spam_detection = defaultdict(list)
        self.raid_detection = defaultdict(list)
        self.auto_mod_settings = {}
        self.muted_roles = {}
        self.setup_logging()

    def setup_logging(self):
        self.logger = logging.getLogger('mod_bot')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('mod_logs.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.logger.addHandler(handler)

# Utility Functions
def get_current_time():
    """Get current UTC time in timezone-aware format"""
    return datetime.now(timezone.utc)

async def create_muted_role(guild):
    """Create and set up muted role"""
    muted_role = await guild.create_role(name="Muted", reason="Auto-created muted role")
    for channel in guild.channels:
        await channel.set_permissions(muted_role, 
                                    send_messages=False,
                                    add_reactions=False,
                                    speak=False)
    return muted_role

async def get_muted_role(guild):
    """Get or create muted role"""
    role = discord.utils.get(guild.roles, name="Muted")
    if not role:
        role = await create_muted_role(guild)
    return role

async def log_action(guild: discord.Guild, action: str, moderator: discord.Member, user: discord.Member, reason: str):
    """Log moderation actions"""
    log_channel = discord.utils.get(guild.channels, name="mod-logs")
    if not log_channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        log_channel = await guild.create_text_channel('mod-logs', overwrites=overwrites)

    embed = discord.Embed(
        title=f"Moderation Action: {action}",
        description=f"**Target:** {user.mention} ({user.id})\n"
                   f"**Moderator:** {moderator.mention}\n"
                   f"**Reason:** {reason}",
        color=discord.Color.red(),
        timestamp=get_current_time()
    )
    await log_channel.send(embed=embed)
    bot.logger.info(f"{action}: {user.name} ({user.id}) by {moderator.name} for {reason}")

# Help Command
@bot.group(invoke_without_command=True)
async def help(ctx):
    """Show help information"""
    embed = discord.Embed(
        title="Moderator Bot Help",
        description="Use !help <command> for detailed information about a command.",
        color=discord.Color.blue()
    )
    
    command_groups = {
        "Basic Moderation": ["warn", "mute", "unmute", "timeout", "kick", "ban", "unban", "purge"],
        "Auto-Moderation": ["raid_protect", "set_filter", "lockdown", "unlock"],
        "Information": ["userinfo", "serverinfo", "warnings"]
    }
    
    for group, commands_list in command_groups.items():
        embed.add_field(
            name=group,
            value="\n".join([f"`!{cmd}`" for cmd in commands_list]),
            inline=False
        )
    
    await ctx.send(embed=embed)

# Basic Moderation Commands
@bot.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: Optional[discord.Member] = None, *, reason="No reason provided"):
    """Warn a member"""
    if not member:
        embed = discord.Embed(
            title="Command Help: Warn",
            description="Warn a member with optional reason",
            color=discord.Color.blue()
        )
        embed.add_field(name="Usage", value="!warn @member [reason]")
        embed.add_field(name="Example", value="!warn @user Spamming in chat")
        await ctx.send(embed=embed)
        return

    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot warn members with equal or higher role!")
        return

    bot.warning_counts[member.id] += 1
    warning_count = bot.warning_counts[member.id]
    
    # Warning escalation system
    escalation_msg = ""
    if warning_count >= 5:
        await member.ban(reason=f"Exceeded warning limit: {reason}")
        escalation_msg = "User has been banned for exceeding warning limit."
    elif warning_count >= 3:
        await member.timeout(timedelta(hours=24), reason=f"Multiple warnings: {reason}")
        escalation_msg = "User has been timed out for 24 hours."

    await log_action(ctx.guild, "Warning", ctx.author, member, reason)
    
    # Notify the warned user
    warn_embed = discord.Embed(
        title="Warning Notice",
        description=f"You have been warned in {ctx.guild.name}",
        color=discord.Color.orange()
    )
    warn_embed.add_field(name="Reason", value=reason)
    warn_embed.add_field(name="Warning Count", value=f"{warning_count}/5")
    if escalation_msg:
        warn_embed.add_field(name="Action Taken", value=escalation_msg, inline=False)
    
    try:
        await member.send(embed=warn_embed)
    except discord.Forbidden:
        await ctx.send("Note: Could not DM user about the warning.")

    await ctx.send(f"✅ {member.mention} has been warned. Warning count: {warning_count}/5\n{escalation_msg}")

@bot.command()
@commands.has_permissions(kick_members=True)
async def mute(ctx, member: Optional[discord.Member] = None, duration: Optional[str] = None, *, reason="No reason provided"):
    """Mute a member"""
    if not member or not duration:
        embed = discord.Embed(
            title="Command Help: Mute",
            description="Mute a member for a specified duration",
            color=discord.Color.blue()
        )
        embed.add_field(name="Usage", value="!mute @member [duration] [reason]")
        embed.add_field(name="Example", value="!mute @user 1h Spamming")
        embed.add_field(name="Duration Format", value="s (seconds), m (minutes), h (hours), d (days)")
        await ctx.send(embed=embed)
        return

    # Parse duration
    time_conversion = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    try:
        duration_unit = duration[-1].lower()
        duration_value = int(duration[:-1])
        seconds = duration_value * time_conversion[duration_unit]
        if seconds > 86400 * 28:  # Discord's max timeout is 28 days
            await ctx.send("❌ Mute duration cannot exceed 28 days!")
            return
    except (ValueError, KeyError, IndexError):
        await ctx.send("❌ Invalid duration format! Use: 1s, 1m, 1h, 1d")
        return

    muted_role = await get_muted_role(ctx.guild)
    await member.add_roles(muted_role, reason=reason)
    
    # Schedule unmute
    await log_action(ctx.guild, "Mute", ctx.author, member, f"{duration} - {reason}")
    await ctx.send(f"✅ {member.mention} has been muted for {duration}")
    
    await asyncio.sleep(seconds)
    if muted_role in member.roles:
        await member.remove_roles(muted_role, reason="Mute duration expired")
        await ctx.send(f"✅ {member.mention} has been automatically unmuted")

@bot.command()
@commands.has_permissions(kick_members=True)
async def unmute(ctx, member: Optional[discord.Member] = None):
    """Unmute a member"""
    if not member:
        embed = discord.Embed(
            title="Command Help: Unmute",
            description="Unmute a previously muted member",
            color=discord.Color.blue()
        )
        embed.add_field(name="Usage", value="!unmute @member")
        embed.add_field(name="Example", value="!unmute @user")
        await ctx.send(embed=embed)
        return

    muted_role = await get_muted_role(ctx.guild)
    if muted_role not in member.roles:
        await ctx.send("❌ The user is not muted!")
        return
    
    await member.remove_roles(muted_role, reason="Unmute command issued")
    await ctx.send(f"✅ {member.mention} has been unmuted.")

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kick a member"""
    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot kick members with equal or higher role!")
        return

    await member.kick(reason=reason)
    await log_action(ctx.guild, "Kick", ctx.author, member, reason)
    await ctx.send(f"✅ {member.mention} has been kicked for {reason}")

# Run the bot
bot = ModBot()
bot.run('YOUR_BOT_TOKEN')
