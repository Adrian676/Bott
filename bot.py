import os
import json
import time
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

import os
import asyncio
from aiohttp import web

async def health_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/health", lambda r: web.Response(text="ok"))

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

load_dotenv()


# -------------------------
# Config helpers
# -------------------------
def load_config(path: str = "config.json") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: Dict[str, Any], path: str = "config.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = load_config()


def cfg_int(key: str) -> int:
    v = CONFIG.get(key, 0)
    return int(v) if v else 0


# -------------------------
# Intents
# -------------------------
intents = discord.Intents.default()
intents.message_content = True  # necessário para comandos e moderação básica
intents.members = True          # necessário para boas-vindas e cargos

bot = commands.Bot(command_prefix="!", intents=intents)

def parse_channel_id_from_mention(text: str) -> int:
    # <#123>
    m = re.search(r"<#(\d+)>", text)
    return int(m.group(1)) if m else 0

def parse_role_id_from_mention(text: str) -> int:
    # <@&123>
    m = re.search(r"<@&(\d+)>", text)
    return int(m.group(1)) if m else 0

async def ask(ctx: commands.Context, question: str, parser, timeout: int = 90) -> int:
    await ctx.send(question)

    def check(msg: discord.Message):
        return msg.author == ctx.author and msg.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", timeout=timeout, check=check)
    except asyncio.TimeoutError:
        await ctx.send("⏱️ Tempo esgotado. Rode `!setup` de novo quando quiser.")
        return 0

    value = parser(msg.content.strip())
    if not value and msg.content.strip().lower() not in ("pular", "skip"):
        await ctx.send("⚠️ Não entendi. Responda mencionando corretamente ou digite `pular`.")
        return await ask(ctx, question, parser, timeout=timeout)

    return value

@bot.command()
@commands.has_permissions(manage_guild=True)
async def setup(ctx: commands.Context):
    """
    Wizard de configuração: preenche config.json por perguntas.
    Responda mencionando canal/cargo/categoria, ou digite 'pular'.
    """
    await ctx.send(
        "🧩 **Setup do Python Dev Lab Bot**\n"
        "Vou te fazer algumas perguntas.\n"
        "Responda mencionando o canal/cargo/categoria, ou digite `pular`.\n"
        "Você pode cancelar digitando `cancelar` (não salva)."
    )

    # função auxiliar de cancelamento
    def is_cancel(text: str) -> bool:
        return text.strip().lower() in ("cancelar", "cancel", "stop")

    # Perguntas
    # 1) Canal de logs
    v = await ask(
        ctx,
        "1/6) Marque o **canal de logs** (ex: <#canal-logs>)",
        parse_channel_id_from_mention
    )
    if v and not is_cancel(str(v)):
        CONFIG["log_channel_id"] = v

    # 2) Canal de boas-vindas
    v = await ask(
        ctx,
        "2/6) Marque o **canal de boas-vindas** (ex: <#boas-vindas>)",
        parse_channel_id_from_mention
    )
    if v:
        CONFIG["welcome_channel_id"] = v

    # 3) Cargo padrão ao entrar
    v = await ask(
        ctx,
        "3/6) Marque o **cargo padrão** para novos membros (ex: <@&Iniciante>)",
        parse_role_id_from_mention
    )
    if v:
        CONFIG["default_role_id"] = v

    # 4) Categoria de tickets (categoria também é “canal” para menção)
    v = await ask(
        ctx,
        "4/6) Marque a **categoria de tickets** (ex: <#Tickets>)",
        parse_channel_id_from_mention
    )
    if v:
        CONFIG["ticket_category_id"] = v

    # 5) Cargo da equipe que vê tickets
    v = await ask(
        ctx,
        "5/6) Marque o **cargo de suporte** que verá tickets (ex: <@&Mod> ou <@&Mentor>)",
        parse_role_id_from_mention
    )
    if v:
        CONFIG["ticket_support_role_id"] = v

    # 6) Canal de desafios
    v = await ask(
        ctx,
        "6/6) Marque o **canal de desafios** (ex: <#desafios-python>)",
        parse_channel_id_from_mention
    )
    if v:
        CONFIG["challenge_channel_id"] = v

    # Salvar
    save_config(CONFIG)
    await ctx.send(
        "✅ **Configuração salva!**\n"
        "Sugestão: reinicie o serviço no Render para garantir que tudo carregou.\n"
        "Teste com `!ping` e `!ticket abrir teste`."
    )

@setup.error
async def setup_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("⚠️ Você precisa de permissão **Gerenciar Servidor** para usar `!setup`.")
    raise error

# -------------------------
# Utility: logging
# -------------------------
async def log_event(message: str) -> None:
    log_channel_id = cfg_int("log_channel_id")
    if not log_channel_id:
        return
    ch = bot.get_channel(log_channel_id)
    if isinstance(ch, discord.TextChannel):
        await ch.send(message)


# -------------------------
# READY
# -------------------------
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="Python Dev Lab"))
    print(f"✅ Logado como: {bot.user} (ID: {bot.user.id})")
    await log_event("✅ Bot online.")


# -------------------------
# MEMBER JOIN / LEAVE
# -------------------------
@bot.event
async def on_member_join(member: discord.Member):
    welcome_channel_id = cfg_int("welcome_channel_id")
    default_role_id = cfg_int("default_role_id")

    # Mensagem de boas-vindas
    if welcome_channel_id:
        ch = member.guild.get_channel(welcome_channel_id)
        if isinstance(ch, discord.TextChannel):
            await ch.send(
                f"👋 Bem-vindo(a), {member.mention}!\n"
                f"Comece por `🎁┃codigo-gratis` e depois escolha seu canal de nível.\n"
                f"Se precisar de ajuda, use `🆘┃ajuda-python`."
            )

    # Cargo padrão (opcional)
    if default_role_id:
        role = member.guild.get_role(default_role_id)
        if role:
            try:
                await member.add_roles(role, reason="Cargo padrão ao entrar")
            except discord.Forbidden:
                await log_event("⚠️ Sem permissão para adicionar cargos (verifique role hierarchy).")

    await log_event(f"➡️ Entrou: {member} ({member.id})")


@bot.event
async def on_member_remove(member: discord.Member):
    await log_event(f"⬅️ Saiu: {member} ({member.id})")


# -------------------------
# BASIC MODERATION (simple anti-link / anti-flood)
# -------------------------
# Anti-flood simples (por usuário)
_last_message_time: Dict[int, float] = {}
_last_message_count: Dict[int, int] = {}

FLOOD_WINDOW_SEC = 4
FLOOD_MAX_MSG = 5

SUSPICIOUS_DOMAINS = {
    "bit.ly", "grabify", "iplogger", "tinyurl.com"
}

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # anti-flood
    now = time.time()
    uid = message.author.id
    prev = _last_message_time.get(uid, 0)

    if now - prev <= FLOOD_WINDOW_SEC:
        _last_message_count[uid] = _last_message_count.get(uid, 0) + 1
    else:
        _last_message_count[uid] = 1

    _last_message_time[uid] = now

    if _last_message_count.get(uid, 0) >= FLOOD_MAX_MSG:
        try:
            await message.channel.send(f"⚠️ {message.author.mention}, evite flood.")
            await log_event(f"⚠️ Flood detectado: {message.author} em #{message.channel}")
        except:
            pass

    # anti-link suspeito
    content_lower = message.content.lower()
    if "http://" in content_lower or "https://" in content_lower:
        for d in SUSPICIOUS_DOMAINS:
            if d in content_lower:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, link bloqueado por segurança."
                    )
                    await log_event(f"🛡️ Link suspeito removido de {message.author} em #{message.channel}: {d}")
                except discord.Forbidden:
                    await log_event("⚠️ Sem permissão para apagar mensagens (ver permissões do bot).")
                break

    await bot.process_commands(message)


# -------------------------
# COMMANDS: util
# -------------------------
@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx: commands.Context, amount: int = 10):
    amount = max(1, min(amount, 200))
    deleted = await ctx.channel.purge(limit=amount + 1)
    await log_event(f"🧹 {ctx.author} limpou {len(deleted)-1} msgs em #{ctx.channel}")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx: commands.Context):
    overwrites = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrites.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrites)
    await ctx.send("🔒 Canal trancado.")
    await log_event(f"🔒 {ctx.author} trancou #{ctx.channel}")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx: commands.Context):
    overwrites = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrites.send_messages = True
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrites)
    await ctx.send("🔓 Canal destrancado.")
    await log_event(f"🔓 {ctx.author} destrancou #{ctx.channel}")


@bot.command()
@commands.has_permissions(manage_guild=True)
async def anuncio(ctx: commands.Context, *, texto: str):
    # manda no canal de anúncios oficial (se configurado), senão no atual
    target_id = cfg_int("anuncios_channel_id") if "anuncios_channel_id" in CONFIG else 0
    ch = bot.get_channel(target_id) if target_id else ctx.channel
    if isinstance(ch, discord.TextChannel):
        await ch.send(f"📢 **Anúncio**\n{texto}")
        await log_event(f"📢 Anúncio por {ctx.author} em #{ch}")


# -------------------------
# TICKETS
# -------------------------
@bot.group(invoke_without_command=True)
async def ticket(ctx: commands.Context):
    await ctx.send(
        "🎫 Use: `!ticket abrir <motivo>` ou `!ticket fechar` (dentro do ticket)."
    )


@ticket.command(name="abrir")
async def ticket_abrir(ctx: commands.Context, *, motivo: str = "Sem motivo informado"):
    category_id = cfg_int("ticket_category_id")
    support_role_id = cfg_int("ticket_support_role_id")

    category = ctx.guild.get_channel(category_id) if category_id else None
    if category_id and not isinstance(category, discord.CategoryChannel):
        return await ctx.send("⚠️ `ticket_category_id` inválido no config.json.")

    support_role = ctx.guild.get_role(support_role_id) if support_role_id else None

    # cria canal
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    channel_name = f"ticket-{ctx.author.name}".lower().replace(" ", "-")
    ticket_channel = await ctx.guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Ticket aberto por {ctx.author}"
    )

    await ticket_channel.send(
        f"🎫 Ticket aberto por {ctx.author.mention}\n"
        f"**Motivo:** {motivo}\n\n"
        f"Um membro da equipe responderá em breve.\n"
        f"Para fechar: `!ticket fechar`"
    )
    await ctx.send(f"✅ Ticket criado: {ticket_channel.mention}")
    await log_event(f"🎫 Ticket criado por {ctx.author} -> #{ticket_channel} | Motivo: {motivo}")


@ticket.command(name="fechar")
async def ticket_fechar(ctx: commands.Context):
    if not ctx.channel.name.startswith("ticket-"):
        return await ctx.send("⚠️ Use este comando dentro de um canal de ticket.")

    await log_event(f"🎫 Ticket fechado por {ctx.author} -> #{ctx.channel}")
    await ctx.send("✅ Ticket será fechado em 3 segundos…")
    await discord.utils.sleep_until(discord.utils.utcnow() + discord.timedelta(seconds=3))
    await ctx.channel.delete(reason=f"Ticket fechado por {ctx.author}")


# -------------------------
# DESAFIOS
# -------------------------
@bot.group(invoke_without_command=True)
async def desafio(ctx: commands.Context):
    await ctx.send("🧠 Use: `!desafio postar <texto>` | `!desafio enviar <link ou descrição>` | `!desafio lista`")


# simples storage em memória (se reiniciar, perde; depois podemos persistir em SQLite)
current_challenge: Optional[str] = None
submissions: Dict[int, str] = {}


@desafio.command(name="postar")
@commands.has_permissions(manage_guild=True)
async def desafio_postar(ctx: commands.Context, *, texto: str):
    global current_challenge, submissions
    current_challenge = texto
    submissions = {}

    challenge_channel_id = cfg_int("challenge_channel_id")
    ch = bot.get_channel(challenge_channel_id) if challenge_channel_id else ctx.channel

    if isinstance(ch, discord.TextChannel):
        await ch.send(
            "🧠 **Desafio da Semana**\n"
            f"{texto}\n\n"
            "✅ Para enviar sua solução: `!desafio enviar <link/descrição>`\n"
            "📌 Dica: explique em 1 frase o que seu script faz."
        )
        await log_event(f"🧠 Desafio postado por {ctx.author} em #{ch}")


@desafio.command(name="enviar")
async def desafio_enviar(ctx: commands.Context, *, solucao: str):
    global submissions
    if not current_challenge:
        return await ctx.send("⚠️ Ainda não há desafio ativo. Aguarde o próximo.")

    submissions[ctx.author.id] = solucao
    await ctx.send("✅ Solução registrada. Obrigado por participar!")
    await log_event(f"🧠 Submissão: {ctx.author} -> {solucao}")


@desafio.command(name="lista")
async def desafio_lista(ctx: commands.Context):
    if not current_challenge:
        return await ctx.send("⚠️ Ainda não há desafio ativo.")

    if not submissions:
        return await ctx.send("🧠 Desafio ativo, mas ainda sem submissões.")

    lines = []
    for uid, s in submissions.items():
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else str(uid)
        lines.append(f"- **{name}**: {s}")

    await ctx.send("📋 **Submissões:**\n" + "\n".join(lines))


# -------------------------
# Error handling
# -------------------------
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("⚠️ Você não tem permissão para isso.")
    if isinstance(error, commands.CommandNotFound):
        return  # silencioso
    await ctx.send("⚠️ Ocorreu um erro ao executar o comando.")
    await log_event(f"❌ Erro: {error}")


# -------------------------
# Run
# -------------------------
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN não encontrado no .env")

@bot.event
async def on_ready():
    asyncio.create_task(health_server())
    print(f"✅ Logado como {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))

