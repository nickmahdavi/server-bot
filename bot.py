import dotenv
import discord
import os

from server import (
    Server,
    InstanceError,
    ServerStartError,
    NetworkingError,
    SERVER_ADDRESS
)

MY_ID = "529480508367699968"
PING_NICK = f"<@{MY_ID}>"

dotenv.load_dotenv()
bot = discord.Bot()
server = bot.create_group("server", "manage Minecraft servers")
srv = Server()

@server.command(description="Start the server")
async def start(ctx):
    await ctx.respond("Starting server. / ☁️ Contacting AWS")

    async def update(stage):
        msg = {
            "instance": "Starting server. / ⚙️ Starting instance",
            "server": "Starting server. / 🚀 Launching server",
            "success": "Starting server. / 🟢 Success",
            "failure": "Starting server. / 🔴 Failed",
        }
        await ctx.edit(content=msg[stage])

    try:
        await srv.start(progress_callback=update)
    except Exception as e:
        msgs = {
            InstanceError: "couldn't get a CPU",
            ServerStartError: "Minecraft didn't load",
            NetworkingError: "bad connection"
        }
        diagnostic = msgs.get(type(e), None)
        import traceback
        traceback.print_exc()
        await ctx.followup.send(f"{ctx.author.mention} Failed to start server ({diagnostic or e}). {PING_NICK} fix this please")
    else:
        await ctx.followup.send(f"{ctx.author.mention} Server started successfully. Connect at {SERVER_ADDRESS}")

@server.command(description="Stop the server")
async def stop(ctx):
    if ctx.author.id != int(MY_ID):
        await ctx.respond(f"You don't have permission to stop the server.")
        return
    
    pass # Similar to start.

def run():
    bot.run(os.getenv("DISCORD_BOT_TOKEN"))

if __name__ == "__main__":
    run()