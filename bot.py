import os
from datetime import datetime, timedelta, timezone

import discord


PANEL_CHANNEL_IDS = {
    1459635692576444511,  # 🎫•ticket
    1460763952504901915,  # 📄•contas
}
TRANSCRIPT_CHANNEL_ID = 1460769731031077059
MOD_PANEL_CHANNEL_ID = TRANSCRIPT_CHANNEL_ID
SUPPORT_ROLE_NAMES = {
    "💰 • Vendedor .",
    "🛡️ • Mod .",
    "🖥️ • Desenvolvedor",
    "🤖 • Bots .",
}


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

WARNINGS: dict[tuple[int, int], list[dict[str, str]]] = {}


def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str) -> None:
    key = (guild_id, user_id)
    entries = WARNINGS.setdefault(key, [])
    entries.append(
        {
            "moderator_id": str(moderator_id),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


class TicketView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir ticket", style=discord.ButtonStyle.green, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este botao em um servidor.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Canal do painel invalido.", ephemeral=True)
            return

        if interaction.channel.id not in PANEL_CHANNEL_IDS:
            await interaction.response.send_message("Este painel nao esta autorizado.", ephemeral=True)
            return

        category = interaction.channel.category
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }

        for role_name in SUPPORT_ROLE_NAMES:
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                )

        channel_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Ticket de {interaction.user} ({interaction.user.id})",
        )

        await ticket_channel.send(
            content=f"{interaction.user.mention} seu ticket foi criado.",
            view=CloseTicketView(),
        )
        await interaction.response.send_message(
            f"Ticket criado: {ticket_channel.mention}",
            ephemeral=True,
        )


class CloseTicketView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Este botao so funciona em um ticket.", ephemeral=True)
            return

        await interaction.response.send_message("Fechando ticket e gerando transcript...", ephemeral=True)

        transcript_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
        transcript_lines: list[str] = []

        async for message in interaction.channel.history(limit=None, oldest_first=True):
            timestamp = message.created_at.strftime("%H:%M")
            author = f"{message.author.display_name} ({message.author.id})"
            content = message.content.strip() if message.content else ""
            if message.attachments:
                attachments = " ".join(f"[anexo]({a.url})" for a in message.attachments)
                content = f"{content} {attachments}".strip()
            if not content:
                content = "*sem texto*"
            transcript_lines.append(f"- `{timestamp}` **{author}**: {content}")

        if isinstance(transcript_channel, discord.TextChannel):
            closed_at = datetime.now(timezone.utc)
            created_at = interaction.channel.created_at.astimezone(timezone.utc)
            header = (
                f"**Canal:** {interaction.channel.mention}\n"
                f"**Aberto em:** {created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"**Fechado por:** {interaction.user.mention}\n"
                f"**Fechado em:** {closed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"**Mensagens:** {len(transcript_lines)}"
            )
            chunks = chunk_lines(transcript_lines)
            base_embed = discord.Embed(
                title="Transcript do Ticket",
                description=header,
                color=discord.Color.from_str("#00C2A8"),
                timestamp=closed_at,
            )
            if interaction.guild and interaction.guild.icon:
                base_embed.set_thumbnail(url=interaction.guild.icon.url)
            base_embed.set_footer(text=f"Ticket ID: {interaction.channel.id}")
            view = TranscriptView(
                transcript_chunks=chunks,
                ticket_channel_name=interaction.channel.name,
            )
            await transcript_channel.send(embed=base_embed, view=view)

        await interaction.channel.delete(reason="Ticket fechado")


class TranscriptView(discord.ui.View):
    def __init__(self, transcript_chunks: list[str], ticket_channel_name: str) -> None:
        super().__init__(timeout=None)
        self.transcript_chunks = transcript_chunks
        self.ticket_channel_name = ticket_channel_name
        self.sent = False

    @discord.ui.button(label="Ver transcript", style=discord.ButtonStyle.secondary, custom_id="transcript_open")
    async def open_transcript(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.sent:
            await interaction.response.send_message("Transcript ja foi aberto.", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Canal de transcript invalido.", ephemeral=True)
            return

        thread_name = f"transcript-{self.ticket_channel_name}".lower()[:90]
        thread = await interaction.channel.create_thread(
            name=thread_name,
            message=interaction.message,
        )
        self.sent = True

        if not self.transcript_chunks:
            await thread.send("Sem mensagens registradas no ticket.")
        else:
            for index, chunk in enumerate(self.transcript_chunks, start=1):
                embed = discord.Embed(
                    title=f"Mensagens ({index}/{len(self.transcript_chunks)})",
                    description=chunk,
                    color=discord.Color.from_str("#00C2A8"),
                )
                await thread.send(embed=embed)

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)


class ModeratorPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user.guild_permissions.administrator)

    @discord.ui.button(label="Configuracoes do bot", style=discord.ButtonStyle.primary, custom_id="panel_config")
    async def show_config(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel em um servidor.", ephemeral=True)
            return

        support_roles = ", ".join(SUPPORT_ROLE_NAMES)
        embed = discord.Embed(
            title="Configuracoes do bot",
            description="Resumo rapido das configuracoes ativas.",
            color=discord.Color.from_str("#3B82F6"),
        )
        embed.add_field(name="Canais de painel", value=", ".join(str(i) for i in PANEL_CHANNEL_IDS), inline=False)
        embed.add_field(name="Canal de transcript", value=str(TRANSCRIPT_CHANNEL_ID), inline=False)
        embed.add_field(name="Roles de suporte", value=support_roles or "nenhuma", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Comandos de moderacao", style=discord.ButtonStyle.secondary, custom_id="panel_commands")
    async def show_commands(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="Comandos de moderacao",
            description=(
                "`/kick`, `/ban`, `/unban`, `/timeout`, `/untimeout`, `/purge`, "
                "`/warn`, `/warnings`, `/lock`, `/unlock`, `/slowmode`"
            ),
            color=discord.Color.from_str("#3B82F6"),
        )
        embed.set_footer(text="Somente administradores podem executar.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.select(
        placeholder="Acoes rapidas",
        custom_id="panel_quick_actions",
        options=[
            discord.SelectOption(label="Limpar 10 mensagens", value="purge_10"),
            discord.SelectOption(label="Limpar 25 mensagens", value="purge_25"),
            discord.SelectOption(label="Travar canal", value="lock"),
            discord.SelectOption(label="Destravar canal", value="unlock"),
            discord.SelectOption(label="Slowmode 5s", value="slowmode_5"),
            discord.SelectOption(label="Slowmode OFF", value="slowmode_0"),
        ],
    )
    async def quick_actions(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("Somente administradores podem usar.", ephemeral=True)
            return

        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Canal invalido.", ephemeral=True)
            return

        choice = select.values[0]
        if choice == "purge_10":
            await interaction.response.defer(ephemeral=True)
            deleted = await interaction.channel.purge(limit=10)
            await interaction.followup.send(f"Foram removidas {len(deleted)} mensagens.", ephemeral=True)
        elif choice == "purge_25":
            await interaction.response.defer(ephemeral=True)
            deleted = await interaction.channel.purge(limit=25)
            await interaction.followup.send(f"Foram removidas {len(deleted)} mensagens.", ephemeral=True)
        elif choice == "lock":
            await interaction.channel.set_permissions(
                interaction.guild.default_role,
                send_messages=False,
            )
            await interaction.response.send_message("Canal travado.", ephemeral=True)
        elif choice == "unlock":
            await interaction.channel.set_permissions(
                interaction.guild.default_role,
                send_messages=None,
            )
            await interaction.response.send_message("Canal destravado.", ephemeral=True)
        elif choice == "slowmode_5":
            await interaction.channel.edit(slowmode_delay=5)
            await interaction.response.send_message("Slowmode 5s ativado.", ephemeral=True)
        elif choice == "slowmode_0":
            await interaction.channel.edit(slowmode_delay=0)
            await interaction.response.send_message("Slowmode desativado.", ephemeral=True)


def chunk_lines(lines: list[str], max_chars: int = 3900) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line_size = len(line) + 1
        if size + line_size > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks


class TicketBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.add_view(TicketView())
        self.add_view(CloseTicketView())
        self.add_view(ModeratorPanelView())
        self.tree.add_command(kick_command)
        self.tree.add_command(ban_command)
        self.tree.add_command(unban_command)
        self.tree.add_command(timeout_command)
        self.tree.add_command(untimeout_command)
        self.tree.add_command(purge_command)
        self.tree.add_command(warn_command)
        self.tree.add_command(warnings_command)
        self.tree.add_command(lock_command)
        self.tree.add_command(unlock_command)
        self.tree.add_command(slowmode_command)
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Bot conectado como {self.user}")
        await self.ensure_panel()
        await self.ensure_moderator_panel()

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, discord.app_commands.CheckFailure):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Voce nao tem permissao para usar este comando.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Voce nao tem permissao para usar este comando.",
                    ephemeral=True,
                )
            return
        if interaction.response.is_done():
            await interaction.followup.send("Erro ao executar o comando.", ephemeral=True)
        else:
            await interaction.response.send_message("Erro ao executar o comando.", ephemeral=True)

    async def ensure_panel(self) -> None:
        for channel_id in PANEL_CHANNEL_IDS:
            channel = self.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            async for message in channel.history(limit=25):
                if message.author == self.user and message.components:
                    break
            else:
                embed = discord.Embed(
                    title="Central de Tickets",
                    description="Clique no botao abaixo para abrir um ticket.",
                    color=discord.Color.blurple(),
                )
                await channel.send(embed=embed, view=TicketView())

    async def ensure_moderator_panel(self) -> None:
        channel = self.get_channel(MOD_PANEL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return

        async for message in channel.history(limit=25):
            if message.author == self.user and message.embeds:
                if message.embeds[0].title == "Painel de Moderacao":
                    return

        embed = discord.Embed(
            title="Painel de Moderacao",
            description="Use os botoes e o menu para acessar configuracoes e acoes rapidas.",
            color=discord.Color.from_str("#3B82F6"),
        )
        await channel.send(embed=embed, view=ModeratorPanelView())


async def send_mod_log(guild: discord.Guild, content: str) -> None:
    channel = guild.get_channel(MOD_PANEL_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(content)


@discord.app_commands.command(name="kick", description="Expulsa um membro do servidor.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def kick_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
) -> None:
    await user.kick(reason=reason)
    await interaction.response.send_message(f"{user.mention} foi expulso.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Kick: {user} por {interaction.user}. Motivo: {reason or 'n/a'}")


@discord.app_commands.command(name="ban", description="Bane um membro do servidor.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def ban_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
) -> None:
    await user.ban(reason=reason, delete_message_days=0)
    await interaction.response.send_message(f"{user.mention} foi banido.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Ban: {user} por {interaction.user}. Motivo: {reason or 'n/a'}")


@discord.app_commands.command(name="unban", description="Remove o ban de um usuario.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def unban_command(
    interaction: discord.Interaction,
    user: discord.User,
    reason: str | None = None,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
        return
    await interaction.guild.unban(user, reason=reason)
    await interaction.response.send_message(f"{user} foi desbanido.", ephemeral=True)
    await send_mod_log(interaction.guild, f"Unban: {user} por {interaction.user}. Motivo: {reason or 'n/a'}")


@discord.app_commands.command(name="timeout", description="Aplica timeout em um membro.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def timeout_command(
    interaction: discord.Interaction,
    user: discord.Member,
    minutos: discord.app_commands.Range[int, 1, 10080],
    reason: str | None = None,
) -> None:
    until = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    await user.edit(timeout=until, reason=reason)
    await interaction.response.send_message(f"{user.mention} recebeu timeout por {minutos} min.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(
            interaction.guild,
            f"Timeout: {user} por {interaction.user} ({minutos} min). Motivo: {reason or 'n/a'}",
        )


@discord.app_commands.command(name="untimeout", description="Remove o timeout de um membro.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def untimeout_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
) -> None:
    await user.edit(timeout=None, reason=reason)
    await interaction.response.send_message(f"Timeout removido de {user.mention}.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Untimeout: {user} por {interaction.user}. Motivo: {reason or 'n/a'}")


@discord.app_commands.command(name="purge", description="Remove mensagens do canal.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def purge_command(
    interaction: discord.Interaction,
    quantidade: discord.app_commands.Range[int, 1, 100],
) -> None:
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Canal invalido.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"Foram removidas {len(deleted)} mensagens.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Purge: {len(deleted)} mensagens por {interaction.user}.")


@discord.app_commands.command(name="warn", description="Adiciona um aviso a um membro.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def warn_command(
    interaction: discord.Interaction,
    user: discord.Member,
    reason: str | None = None,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
        return
    reason_text = reason or "sem motivo"
    add_warning(interaction.guild.id, user.id, interaction.user.id, reason_text)
    await interaction.response.send_message(f"{user.mention} recebeu um aviso.", ephemeral=True)
    await send_mod_log(
        interaction.guild,
        f"Warn: {user} por {interaction.user}. Motivo: {reason_text}",
    )


@discord.app_commands.command(name="warnings", description="Lista avisos de um membro.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def warnings_command(
    interaction: discord.Interaction,
    user: discord.Member,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
        return
    key = (interaction.guild.id, user.id)
    entries = WARNINGS.get(key, [])
    if not entries:
        await interaction.response.send_message(f"{user.mention} nao tem avisos.", ephemeral=True)
        return
    lines = [
        f"{index}. {entry['timestamp']} por {entry['moderator_id']}: {entry['reason']}"
        for index, entry in enumerate(entries, start=1)
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@discord.app_commands.command(name="lock", description="Trava o canal atual.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def lock_command(interaction: discord.Interaction) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Canal invalido.", ephemeral=True)
        return
    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=False,
    )
    await interaction.response.send_message("Canal travado.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Lock: {interaction.channel} por {interaction.user}.")


@discord.app_commands.command(name="unlock", description="Destrava o canal atual.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def unlock_command(interaction: discord.Interaction) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Canal invalido.", ephemeral=True)
        return
    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=None,
    )
    await interaction.response.send_message("Canal destravado.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(interaction.guild, f"Unlock: {interaction.channel} por {interaction.user}.")


@discord.app_commands.command(name="slowmode", description="Configura o modo lento do canal.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def slowmode_command(
    interaction: discord.Interaction,
    segundos: discord.app_commands.Range[int, 0, 21600],
) -> None:
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Canal invalido.", ephemeral=True)
        return
    await interaction.channel.edit(slowmode_delay=segundos)
    await interaction.response.send_message(f"Slowmode ajustado para {segundos}s.", ephemeral=True)
    if interaction.guild:
        await send_mod_log(
            interaction.guild,
            f"Slowmode: {segundos}s em {interaction.channel} por {interaction.user}.",
        )


def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Defina a variavel de ambiente DISCORD_BOT_TOKEN com o token do bot."
        )

    TicketBot().run(token)


if __name__ == "__main__":
    main()
