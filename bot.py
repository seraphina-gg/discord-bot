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

    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: Optional[discord.Member] = None, *, reason="No reason provided"):
        """Kick a member"""
        if not member:
            embed = discord.Embed(
                title="Command Help: Kick",
                description="Kick a member with optional reason",
                color=discord.Color.blue()
            )
            embed.add_field(name="Usage", value="!kick @member [reason]")
            embed.add_field(name="Example", value="!kick @user Violating rules")
            await ctx.send(embed=embed)
            return

        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You cannot kick members with equal or higher role!")
            return

        await member.kick(reason=reason)
        await log_action(ctx.guild, "Kick", ctx.author, member, reason)
        await ctx.send(f"✅ {member.mention} has been kicked. Reason: {reason}")

bot = ModBot()

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
    """
    Warn a member
    Usage: !warn @member [reason]
    Example: !warn @user Spamming in chat
    """
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
    """
    Mute a member
    Usage: !mute @member [duration] [reason]
    Example: !mute @user 1h Spamming
    Duration format: s (seconds), m (minutes), h (hours), d (days)
    """
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
    """
    Unmute a member
    Usage: !unmute @member
    Example: !unmute @user
    """
    if not member:
        embed = discord.Embed(
            title="Command Help: Unmute",
            description="Unmute a member",
            color=discord.Color.blue()
        )
        embed.add_field(name="Usage", value="!unmute @member")
        await ctx.send(embed=embed)
        return

    muted_role = await get_muted_role(ctx.guild)
    if muted_role not in member.roles:
        await ctx.send(f"❌ {member.mention} is not muted!")
        return

    await member.remove_roles(muted_role, reason="Unmute command issued")
    await log_action(ctx.guild, "Unmute", ctx.author, member, "Manual unmute")
    await ctx.send(f"✅ {member.mention} has been unmuted.")

# Running the bot
bot.run('YOUR_BOT_TOKEN')


@commands.command()
@commands.has_permissions(kick_members=True)
async def kick(self, ctx, member: discord.Member = None, *, reason="No reason provided"):
    """
    Kick a user like a football from the server.
    """
    if not member:
        await ctx.send("❌ Please mention a user to kick. You cant kick the Air!")
        return

    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot kick members with an equal or higher role. Sorry lil bro/sis")
        return

    await member.kick(reason=reason)
    await log_action(ctx.guild, "Kick", ctx.author, member, reason)
    await ctx.send(f"✅ {member.mention} has been kicked and you Scored a point +1 Aura")


# Information Commands
@bot.command()
async def userinfo(ctx, member: Optional[discord.Member] = None):
    """Get information about a user"""
    member = member or ctx.author
    
    roles = [role.mention for role in member.roles[1:]]  # Exclude @everyone
    embed = discord.Embed(
        title="User Information",
        color=member.color,
        timestamp=get_current_time()
    )
    
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="User ID", value=member.id)
    embed.add_field(name="Nickname", value=member.nick or "None")
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d"))
    embed.add_field(name="Roles", value=" ".join(roles) if roles else "None", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def serverinfo(ctx):
    """Get information about the server"""
    guild = ctx.guild
    
    embed = discord.Embed(
        title=f"{guild.name} Server Information",
        color=discord.Color.blue(),
        timestamp=get_current_time()
    )
    
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Server ID", value=guild.id)
    embed.add_field(name="Owner", value=guild.owner.mention)
    embed.add_field(name="Created On", value=guild.created_at.strftime("%Y-%m-%d"))
    embed.add_field(name="Member Count", value=guild.member_count)
    embed.add_field(name="Channel Count", value=len(guild.channels))
    embed.add_field(name="Role Count", value=len(guild.roles))
    
    await ctx.send(embed=embed)

# Auto-moderation features
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Process commands first
    await bot.process_commands(message)

    # Spam detection
    current_time = get_current_time()
    bot.spam_detection[message.author.id].append(current_time)
    recent_messages = [
        t for t in bot.spam_detection[message.author.id]
        if (current_time - t).total_seconds() < 5
    ]
    bot.spam_detection[message.author.id] = recent_messages

    if len(recent_messages) >= 5:
        await message.author.timeout(timedelta(minutes=10), reason="Spam detection")
        await message.channel.send(
            embed=discord.Embed(
                title="Auto-Moderation",
                description=f"{message.author.mention} has been timed out for spamming.",
                color=discord.Color.red()
            )
        )
        await log_action(message.guild, "Auto-Timeout", bot.user, message.author, "Spam detection")

    # Bad word filter and more can be added here

@bot.event
async def on_command_error(ctx, error):
    """Enhanced error handling"""
    if isinstance(error, commands.MissingPermissions):
        perms = ', '.join(error.missing_permissions)
        await ctx.send(f"❌ You need the following permissions to use this command: {perms}")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ Could not find member. Please mention a valid member or use their ID.")
    elif isinstance(error, commands.BadArgument):
        if ctx.command:
            await ctx.send_help(ctx.command)
        else:
            await ctx.send("❌ Invalid argument provided! Use !help for command usage.")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")
        bot.logger.error(f"Command error in {ctx.command}: {str(error)}")

@bot.event
async def on_ready():
    print(f"🎉 {bot.user} is now online and ready to rock Discord!")
    activities = [
        "Keeping the chaos in check | Type !help 🎮",
        "Moderating the server | Stay cool 😎",
        "Kicking troublemakers | 😈",
        "Type !help to see what I can do!"
    ]
    
    async def cycle_status():
        while True:
            for activity in activities:
                await bot.change_presence(activity=discord.Game(name=activity))
                await asyncio.sleep(30)  # Waits 30 seconds before changing
    
    bot.loop.create_task(cycle_status())
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            cog_name = f"cogs.{filename[:-3]}"
            try:
               await bot.load_extension(cog_name)
                print(f"✅ Loaded {cog_name}")
            except Exception as e:
                print(f"❌ Failed to load {cog_name}: {e}")

bot.run('')
