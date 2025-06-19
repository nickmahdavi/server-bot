import dotenv
import discord
import os
from aiohttp import web
import asyncio
import re

from server import Server
from config import Config

dotenv.load_dotenv()
config = Config()

srv = Server.from_config(config)

ADMIN_PING = f"<@{config.admin_user_id}>"

bot = discord.Bot()
server = bot.create_group("server", "manage Minecraft servers")

@server.command(description="Start the server")
async def start(ctx):
    await ctx.respond("Starting server. / ☁️ Contacting hosts")

    async def update(stage):
        msg = {
            "instance": "Starting server. / ⚙️ Starting instance",
            "server": "Starting server. / 🚀 Launching server",
            "success": f"Starting server. / 🟢 Success! Connect at {config.server_address}",
            "failure": "Starting server. / 🔴 Failed",
        }
        await ctx.edit(content=msg[stage])

    try:
        await srv.start(progress_callback=update)
    except Exception as e:
        await ctx.followup.send(f"{ctx.author.mention} Failed to start server ({e}). {ADMIN_PING} fix this please")

@server.command(description="Stop the server")
async def stop(ctx):
    if ctx.author.id != int(config.admin_user_id):
        await ctx.respond(f"You don't have permission to stop the server.")
        return
    
    await ctx.respond("Stopping server...")
    try:
        await srv.stop_server()
        await ctx.edit(content="Server stopped successfully.")
    except Exception as e:
        await ctx.followup.send(f"{ctx.author.mention} Failed to stop server: {e}.")

@server.command(description="Stop the server")
async def shutdown(ctx):
    if ctx.author.id != int(config.admin_user_id):
        await ctx.respond(f"You don't have permission to shut down the server.")
        return
    
    await ctx.respond("Shutting down server...")
    try:
        await srv.stop()
        await ctx.edit(content="Server shut down successfully.")
    except Exception as e:
        await ctx.followup.send(f"{ctx.author.mention} Failed to shut down server: {e}.")

@server.command(description="Add player to whitelist")
async def whitelist(ctx, player: discord.Option(str, description="Minecraft username", required=True)):
    # Validate minecraft username (alphanumeric + underscore, 3-16 chars)
    if not re.match(r'^[a-zA-Z0-9_]{3,16}$', player):
        await ctx.respond(f"Invalid username: {player}")
        return
    
    await ctx.defer()  # This might take a second
    
    try:
        result = await srv.send_command(f"sudo -u minecraft screen -S minecraft -X stuff 'whitelist add {player}\r'")
        
        if result["ResponseCode"] == 0:
            await ctx.followup.send(f"✅ Added **{player}** to whitelist!")
        else:
            await ctx.followup.send(f"❌ Failed to add {player}: {result.get('StandardErrorContent', 'Unknown error')}")
            
    except Exception as e:
        await ctx.followup.send(f"Error: {e}")

async def start_server(request):
    try:
        if not await srv.is_ready():
            task = asyncio.create_task(srv.start())
            task.add_done_callback(lambda t: t.exception() if t.exception() else None)
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)
    return web.Response(text="OK", status=200)

async def stop_server(request):
    try:
        if await srv.is_ready():
            task = asyncio.create_task(srv.stop())
            task.add_done_callback(lambda t: t.exception() if t.exception() else None)
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)
    return web.Response(text="OK", status=200)

async def server_status(request):
    try:
        if await srv.is_ready():
            return web.Response(text="Server is running", status=200)
        elif await srv.is_running():
            return web.Response(text="Server is running but not ready", status=202)
        else:
            return web.Response(text="Server is stopped", status=503)
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

async def setup_hook():
    app = web.Application()
    app.router.add_post('/start', start_server)
    app.router.add_post('/stop', stop_server)
    app.router.add_post('/status', server_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.webhook_host, config.webhook_port)
    await site.start()

if __name__ == "__main__":
    bot.setup_hook = setup_hook
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))