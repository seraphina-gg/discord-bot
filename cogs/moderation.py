from discord.ext import commands
import discord
from datetime import timedelta
from utils import get_muted_role, log_action

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

@commands.command()
@commands.has_permissions(kick_members=True)
async def warn(self, ctx, member: discord.Member = None, *, reason="No reason provided"):
    """
    Warn a user. and ban them if exceeds the warn limit.
    """
    if not member:
        await ctx.send("❌ Please mention a member to warn!")
        return

    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot warn members with an equal or higher role.")
        return

    # increment stuff ig
    self.bot.warning_counts[member.id] = self.bot.warning_counts.get(member.id, 0) + 1
    warning_count = self.bot.warning_counts[member.id]

    # WARN ESCALATION LOGIC OVER HERE 
    escalation_message = ""
    if warning_count >= 5:
        await member.ban(reason=f"Exceeded warning limit: {reason}")
        escalation_message = "User has been banned for exceeding the warning limit."
    elif warning_count >= 3:
        await member.timeout(timedelta(hours=24), reason=f"Multiple warnings: {reason}")
        escalation_message = "User has been timed out for 24 hours."

    await log_action(ctx.guild, "Warn", ctx.author, member, reason)

    # Notifies the USER LMFAO
    warn_embed = discord.Embed(
        title="⚠️ Warning",
        description=f"You have been warned in {ctx.guild.name}.",
        color=discord.Color.orange()
    )
    warn_embed.add_field(name="Reason", value=reason)
    warn_embed.add_field(name="Warnings", value=f"{warning_count}/5")
    if escalation_message:
        warn_embed.add_field(name="Action Taken", value=escalation_message)

    try:
        await member.send(embed=warn_embed)
    except discord.Forbidden:
        await ctx.send("❌ Unable to DM the user about the warning.")

    await ctx.send(f"✅ {member.mention} has been warned. Total warnings: {warning_count}/5\n{escalation_message}")


@commands.command()
@commands.has_permissions(kick_members=True)
async def mute(self, ctx, member: discord.Member = None, duration: str = None, *, reason="No reason provided"):
    """
    Mute a user for a specified duration.
    """
    if not member or not duration:
        await ctx.send("❌ Please provide a member and duration (e.g., `!mute @user 1h Spamming`).")
        return

    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot mute members with an equal or higher role.")
        return

    # parse duration logic?
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1]
        value = int(duration[:-1])
        duration_seconds = value * time_units[unit]
    except (ValueError, KeyError):
        await ctx.send("❌ Invalid duration format. Use: `1s`, `1m`, `1h`, or `1d`.")
        return

    muted_role = await get_muted_role(ctx.guild)
    await member.add_roles(muted_role, reason=reason)
    await log_action(ctx.guild, "Mute", ctx.author, member, f"{duration} - {reason}")
    await ctx.send(f"✅ {member.mention} has been muted for {duration}.")

    # Unmutes after duration too :D
    await asyncio.sleep(duration_seconds)
    if muted_role in member.roles:
        await member.remove_roles(muted_role, reason="Mute duration expired.")
        await ctx.send(f"✅ {member.mention} has been unmuted after {duration}.")


    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def unmute(self, ctx, member: discord.Member = None):
        # Umute Soon trademark 
        pass

@commands.command()
@commands.has_permissions(ban_members=True)
async def ban(self, ctx, member: discord.Member = None, *, reason="No reason provided"):
    """
    Ban a user.
    """
    if not member:
        await ctx.send("❌ Please mention a user to ban.")
        return

    if member.top_role >= ctx.author.top_role:
        await ctx.send("❌ You cannot ban members with an equal or higher role.")
        return

    await member.ban(reason=reason)
    await log_action(ctx.guild, "Ban", ctx.author, member, reason)
    await ctx.send(f"✅ {member.mention} has been banned.")

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

@commands.Cog.listener()
async def on_message(self, message):
    if message.author.bot:
        return

    current_time = get_current_time()
    self.bot.spam_detection.setdefault(message.author.id, []).append(current_time)

    # Keep only messages within the last 5 seconds and vanish boom!
    self.bot.spam_detection[message.author.id] = [
        t for t in self.bot.spam_detection[message.author.id]
        if (current_time - t).total_seconds() < 5
    ]

    if len(self.bot.spam_detection[message.author.id]) >= 5:
        await message.author.timeout(timedelta(minutes=10), reason="Spam detection")
        await message.channel.send(f"⛔ {message.author.mention} has been muted for spamming.")
        await log_action(message.guild, "Auto-Mute (Spam)", self.bot.user, message.author, "Spam detection")



def setup(bot):
    bot.add_cog(Moderation(bot))
