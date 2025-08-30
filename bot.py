import os
import json
import time
import random
import asyncio
import requests
import importlib
import importlib.util
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta
import pytz

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from dotenv import load_dotenv
import mercadopago
import codigo2bot
# ----------------- CONFIGURAÇÕES -----------------
load_dotenv("arquivo.env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ML_TOKEN = os.getenv("ML_TOKEN")
ML_PUBLIC_KEY = os.getenv("ML_PUBLIC_KEY")

# Inicializar SDK do Mercado Pago
sdk = mercadopago.SDK(ML_TOKEN)

DB_FILE = "planos_ativos.json"
POST_DB = "posts.json"
PAYMENTS_DB = "pagamentos.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------- PLANOS ATUALIZADOS CONFORME SOLICITADO -----------------
PLANOS = [
    {"id_plano": 1, "descricao": "Vendedor Vermelho 🔴", "tipo": "vendedor", "dias_post": 1, "preco": 25.00},
    {"id_plano": 2, "descricao": "Vendedor Verde 🟢", "tipo": "vendedor", "dias_post": 1, "alternado": True, "preco": 15.90},
    {"id_plano": 3, "descricao": "Vendedor Azul 🔵", "tipo": "vendedor", "dias_post": 2, "preco": 7.90},
    {"id_plano": 4, "descricao": "Destacar Vermelho 🔴", "tipo": "destacar", "tags": "ilimitado", "preco": 75.00},
    {"id_plano": 5, "descricao": "Destacar Verde 🟢", "tipo": "destacar", "tags": 2, "posts_necessarios": 10, "preco": 27.80},
    {"id_plano": 6, "descricao": "Destacar Azul 🔵", "tipo": "destacar", "tags": 1, "posts_necessarios": 10, "preco": 17.80},
    {"id_plano": 7, "descricao": "Comprador Vermelho 🔴", "tipo": "comprador", "dias_post": 1, "preco": 24.90},
    {"id_plano": 8, "descricao": "Comprador Verde 🟢", "tipo": "comprador", "dias_post": 2, "posts_por_periodo": 2, "preco": 12.00},
    {"id_plano": 9, "descricao": "Comprador Azul 🔵", "tipo": "comprador", "dias_post": 2, "preco": 9.50},
]

# Configurações dos canais
CHANNEL_CONFIG = {
    "rede": "🛒rede",
    "recomendacao": "🌟recomendação-do-caveira",
    "destaques": "💯destaques",
    "forum_assinaturas": "assinar🌟",
    "categoria_assinaturas": "📃🌟Assinaturas"
}

# ================== UTILITÁRIOS JSON ==================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        print(f"Erro ao ler {path}, usando valores padrão")
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar {path}: {e}")

def load_planos_db():
    return load_json(DB_FILE, [])

def save_planos_db(data):
    save_json(DB_FILE, data)

def load_payments_db():
    return load_json(PAYMENTS_DB, {})

def save_payments_db(data):
    save_json(PAYMENTS_DB, data)

def load_posts_db():
    return load_json(POST_DB, {})

def save_posts_db(data):
    save_json(POST_DB, data)

# ================== SISTEMA DE FÓRUM PRIVADO ==================
async def obter_ou_criar_thread_privada(user: discord.Member, guild: discord.Guild):
    """Obtém ou cria uma thread privada no fórum de assinaturas para o usuário"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} não encontrada")
            return None
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} não encontrado na categoria")
            return None
        
        if not isinstance(forum_channel, discord.ForumChannel):
            print(f"Canal {CHANNEL_CONFIG['forum_assinaturas']} não é um canal de fórum")
            return None
        
        for thread in forum_channel.threads:
            if thread.name == f"Assinatura - {user.display_name}" or thread.owner_id == user.id:
                return thread
        
        try:
            embed = discord.Embed(
                title=f"🌟 Assinatura Privada - {user.display_name}",
                description="Este é seu espaço privado de assinatura. Apenas você pode ver e interagir aqui.",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="📋 Como usar:",
                value="• Use `!status` para ver seus planos\n• Use `!planos` para comprar novos planos\n• Este chat é totalmente privado",
                inline=False
            )
            embed.set_footer(text="Sistema de Assinaturas Privadas")
            
            thread = await forum_channel.create_thread(
                name=f"Assinatura - {user.display_name}",
                content="",
                embed=embed,
                auto_archive_duration=10080,
                slowmode_delay=0
            )
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            await thread.thread.edit(overwrites=overwrites)
            await thread.thread.add_user(user)
            
            print(f"Thread privada criada para {user.display_name}")
            return thread.thread
            
        except discord.Forbidden:
            print(f"Sem permissão para criar thread no fórum")
            return None
        except Exception as e:
            print(f"Erro ao criar thread: {e}")
            return None
    
    except Exception as e:
        print(f"Erro no sistema de fórum privado: {e}")
        return None

async def garantir_forum_configurado(guild: discord.Guild):
    """Garante que o fórum e categoria estão configurados corretamente"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            try:
                categoria = await guild.create_category(CHANNEL_CONFIG["categoria_assinaturas"])
                print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} criada")
            except discord.Forbidden:
                print("Sem permissão para criar categoria")
                return False
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False
                    ),
                    guild.me: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        create_public_threads=True,
                        create_private_threads=True,
                        manage_threads=True
                    )
                }
                
                forum_channel = await categoria.create_forum(
                    CHANNEL_CONFIG["forum_assinaturas"],
                    topic="Fórum de assinaturas privadas - cada usuário tem seu espaço individual",
                    overwrites=overwrites,
                    slowmode_delay=60
                )
                print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} criado")
            except discord.Forbidden:
                print("Sem permissão para criar fórum")
                return False
            except Exception as e:
                print(f"Erro ao criar fórum: {e}")
                return False
        
        return True
    
    except Exception as e:
        print(f"Erro ao configurar fórum: {e}")
        return False

def pode_postar(user_id: int, tipo_plano: str):
    """Verifica se o usuário pode postar baseado no plano dele - VERSÃO ATUALIZADA"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo
    plano_ativo = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == tipo_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_ativo = plano
            break
    
    if not plano_ativo:
        return False, "Você não possui um plano ativo do tipo necessário."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_ativo["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    user_posts = posts_db.get(str(user_id), {})
    ultimo_post = user_posts.get(f"ultimo_post_{tipo_plano}", 0)
    
    # VENDEDOR VERDE: Sistema alternado (hoje não, amanhã sim)
    if plano_info["id_plano"] == 2:  # Vendedor Verde
        if ultimo_post == 0:  # Primeiro post
            return True, plano_ativo
            
        dias_desde_ultimo = (agora - ultimo_post) // 86400
        if dias_desde_ultimo == 0:  # Mesmo dia do último post
            return False, "Você pode postar novamente amanhã (sistema alternado)."
        elif dias_desde_ultimo >= 1:  # 1+ dias depois - pode postar
            return True, plano_ativo
    
    # COMPRADOR VERDE: 2 posts a cada 2 dias
    elif plano_info["id_plano"] == 8:  # Comprador Verde
        posts_por_periodo = plano_info.get("posts_por_periodo", 2)
        periodo = plano_info.get("dias_post", 2) * 86400  # 2 dias em segundos
        
        posts_no_periodo = user_posts.get(f"posts_periodo_{tipo_plano}", {"inicio": 0, "count": 0})
        
        # Se passou o período, resetar contador
        if agora - posts_no_periodo["inicio"] >= periodo:
            posts_no_periodo = {"inicio": agora, "count": 0}
            user_posts[f"posts_periodo_{tipo_plano}"] = posts_no_periodo
            save_posts_db(posts_db)
        
        # Verificar se ainda pode postar no período atual
        if posts_no_periodo["count"] >= posts_por_periodo:
            tempo_restante = periodo - (agora - posts_no_periodo["inicio"])
            horas_restantes = tempo_restante // 3600
            return False, f"Você já fez {posts_por_periodo} posts neste período. Aguarde {horas_restantes} horas."
        
        return True, plano_ativo
    
    # OUTROS PLANOS: Sistema normal por dias
    else:
        dias_necessarios = plano_info.get("dias_post", 1)
        tempo_espera = dias_necessarios * 86400  # dias em segundos
        
        if agora - ultimo_post < tempo_espera:
            horas_restantes = (tempo_espera - (agora - ultimo_post)) // 3600
            return False, f"Você pode postar novamente em {horas_restantes} horas."
        
        return True, plano_ativo

def calcular_taxa_cancelamento(data_inicio: int, eh_pagamento_unico: bool = False):
    """Calcula taxa de cancelamento baseada no tempo de uso"""
    agora = int(time.time())
    dias_desde_compra = (agora - data_inicio) // 86400
    
    if eh_pagamento_unico:
        return 1.0  # Pagamento único sempre 100% de taxa
    
    if dias_desde_compra < 60:  # Menos de 2 meses
        return 1.0  # 100%
    elif dias_desde_compra < 180:  # 2-6 meses  
        return 0.35  # 35%
    elif dias_desde_compra < 180:  # Mais de 6 meses
        return 0.15  # 15%
    else:
        return 0.0  # Sem taxa após muito tempo
def pode_usar_destaque(user_id: int):
    """Verifica se o usuário pode usar a tag de destaque - VERSÃO ATUALIZADA"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo de destacar
    plano_destacar = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == "destacar" and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_destacar = plano
            break
    
    if not plano_destacar:
        return False, "Você precisa de um plano de destaque para usar esta tag."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_destacar["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    # PLANO VERMELHO: ILIMITADO
    if plano_info["id_plano"] == 4:  # Destacar Vermelho
        return True, plano_destacar
    
    user_posts = posts_db.get(str(user_id), {})
    
    # Para planos Verde e Azul de destaque, verificar posts na rede
    if "posts_necessarios" in plano_info:
        posts_rede = user_posts.get("posts_rede", 0)
        destaques_usados = user_posts.get("destaques_usados", 0)
        
        # Calcular quantos destaques pode usar
        destaques_disponiveis = (posts_rede // plano_info["posts_necessarios"]) * plano_info["tags"]
        
        if destaques_usados >= destaques_disponiveis:
            posts_faltantes = plano_info["posts_necessarios"] - (posts_rede % plano_info["posts_necessarios"])
            return False, f"Você precisa fazer mais {posts_faltantes} posts na 🛒rede para usar destaque novamente."
    
    return True, plano_destacar

def registrar_post(user_id: int, canal_tipo: str, tem_destaque: bool = False):
    """Registra um post do usuário - VERSÃO ATUALIZADA"""
    posts_db = load_posts_db()
    user_posts = posts_db.get(str(user_id), {})
    agora = int(time.time())
    
    # Registrar último post por tipo
    if canal_tipo == "vendedor":
        user_posts["ultimo_post_vendedor"] = agora
        user_posts["posts_rede"] = user_posts.get("posts_rede", 0) + 1
    elif canal_tipo == "comprador":
        user_posts["ultimo_post_comprador"] = agora
        
        # Para comprador verde, atualizar contador do período
        db = load_planos_db()
        for plano in db:
            if (plano["user_id"] == user_id and 
                plano["tipo"] == "comprador" and 
                plano.get("pago", False) and
                plano.get("data_fim", 0) > agora):
                
                plano_info = next((p for p in PLANOS if p["id_plano"] == plano["id_plano"]), None)
                if plano_info and plano_info["id_plano"] == 8:  # Comprador Verde
                    posts_no_periodo = user_posts.get("posts_periodo_comprador", {"inicio": 0, "count": 0})
                    posts_no_periodo["count"] += 1
                    user_posts["posts_periodo_comprador"] = posts_no_periodo
                break
    
    # Registrar uso de destaque
    if tem_destaque:
        user_posts["destaques_usados"] = user_posts.get("destaques_usados", 0) + 1
    
    posts_db[str(user_id)] = user_posts
    save_posts_db(posts_db)

async def mover_para_destaques(message: discord.Message):
    """Move uma mensagem com tag de destaque para o canal de destaques"""
    try:
        guild = message.guild
        canal_destaques = discord.utils.get(guild.channels, name=CHANNEL_CONFIG["destaques"])
        
        if not canal_destaques:
            print(f"Canal {CHANNEL_CONFIG['destaques']} não encontrado")
            return
        
        embed = discord.Embed(
            title="💯 Post em Destaque",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.set_footer(text=f"Original em #{message.channel.name}")
        embed.timestamp = message.created_at
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        
        await canal_destaques.send(embed=embed)
        print(f"Post de {message.author.display_name} movido para destaques")
        
    except Exception as e:
        print(f"Erro ao mover para destaques: {e}")

# ================== MERCADO PAGO ==================
def criar_assinatura_recorrente(plano: dict, user_id: int, username: str):
    """Cria assinatura recorrente mensal (só cartão)"""
    try:
        referencia = f"sub_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        
        subscription_data = {
            "reason": f"Assinatura {plano['descricao']}",
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": plano["preco"],
                "currency_id": "BRL"
            },
            "payer_email": f"user{user_id}@discord.bot",
            "card_token_id": "CARD_TOKEN",  # Obtido do frontend
            "status": "authorized",
            "external_reference": referencia
        }
        
        response = sdk.subscription().create(subscription_data)
        
        if response["status"] == 201:
            return response["response"]
        else:
            print(f"Erro ao criar assinatura: {response}")
            return None
            
    except Exception as e:
        print(f"Erro na assinatura recorrente: {e}")
        return None

def cancelar_assinatura_mp(subscription_id: str):
    """Cancela assinatura no Mercado Pago"""
    try:
        response = sdk.subscription().update(subscription_id, {"status": "cancelled"})
        return response["status"] == 200
    except Exception as e:
        print(f"Erro ao cancelar assinatura MP: {e}")
        return False
def gerar_chave_pix_aleatoria():
    import uuid
    return str(uuid.uuid4())

def criar_preferencia_pagamento(plano: dict, user_id: int, username: str):
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        referencia = f"plano_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        preference_data = {
            "items": [
                {
                    "title": f"Plano {plano['descricao']}",
                    "quantity": 1,
                    "unit_price": plano["preco"],
                    "currency_id": "BRL",
                    "description": f"Plano {plano['tipo']} - Discord Bot"
                }
            ],
            "payer": {
                "name": nome_usuario,
                "surname": "Discord User"
            },
            "payment_methods": {
                "excluded_payment_methods": [],
                "excluded_payment_types": [],
                "installments": 12
            },
            "back_urls": {
                "success": "https://www.cleitodiscord.com/success",
                "failure": "https://www.cleitodiscord.com/failure", 
                "pending": "https://www.cleitodiscord.com/pending"
            },
            "auto_return": "approved",
            "external_reference": referencia,
            "statement_descriptor": "DISCORD_BOT",
            "expires": True,
            "expiration_date_from": agora.isoformat(),
            "expiration_date_to": (agora + timedelta(hours=24)).isoformat()
        }
        
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response["status"] == 201:
            return preference_response["response"]
        else:
            print(f"Erro ao criar preferência: {preference_response}")
            return None
    except Exception as e:
        print(f"Erro ao criar preferência de pagamento: {e}")
        return None

def verificar_pagamento_por_referencia(external_reference):
    try:
        filters = {"external_reference": external_reference}
        search_response = sdk.payment().search(filters)
        
        if search_response["status"] == 200:
            results = search_response["response"]["results"]
            if results:
                return results[0]
        elif search_response["status"] == 429:
            print("Rate limit atingido - aguardando...")
            time.sleep(5)
            return None
        else:
            print(f"Erro na busca de pagamento: {search_response}")
        return None
    except Exception as e:
        print(f"Erro ao buscar pagamento: {e}")
        return None

def salvar_preferencia_pendente(preference_data, user_id, plano):
    try:
        payments_db = load_payments_db()
        
        payment_record = {
            "preference_id": preference_data["id"],
            "user_id": user_id,
            "plano": plano,
            "amount": plano["preco"],
            "status": "pending",
            "created_date": preference_data["date_created"],
            "checkout_link": preference_data["init_point"],
            "external_reference": preference_data.get("external_reference")
        }
        
        payments_db[str(preference_data["id"])] = payment_record
        save_payments_db(payments_db)
        return payment_record
    except Exception as e:
        print(f"Erro ao salvar preferência pendente: {e}")
        return None

def ativar_plano_apos_pagamento(user_id: int, plano: dict, modalidade: str = "mensal", subscription_id: str = None):
    try:
        db = load_planos_db()
        timestamp = int(time.time())
        duracao = 30 * 86400  # 30 dias
        
        plano_registro = {
            "user_id": user_id,
            "id_plano": plano["id_plano"],
            "descricao": plano["descricao"],
            "tipo": plano["tipo"],
            "pago": True,
            "modalidade": modalidade,
            "data_inicio": timestamp,
            "data_fim": timestamp + duracao,
            "subscription_id": subscription_id,  # Para assinaturas recorrentes
            "cancelado": False
        }
        
        db.append(plano_registro)
        save_planos_db(db)
        return plano_registro
    except Exception as e:
        print(f"Erro ao ativar plano: {e}")
        return None

# ================== ROLES DISCORD ==================
async def ensure_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        try:
            role = await guild.create_role(name=name, color=discord.Color.blue())
            print(f"Cargo '{name}' criado no servidor {guild.name}")
        except discord.Forbidden:
            print(f"Sem permissão para criar cargo: {name}")
            return None
        except Exception as e:
            print(f"Erro ao criar cargo {name}: {e}")
            return None
    return role

async def assign_role_to_member(member: discord.Member, tipo: str):
    try:
        role_name = tipo.capitalize()
        role = await ensure_role(member.guild, role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
            print(f"Cargo '{role_name}' atribuído a {member.display_name}")
            return True
        return True
    except discord.Forbidden:
        print(f"Sem permissão para adicionar cargo a {member.display_name}")
        return False
    except Exception as e:
        print(f"Erro ao atribuir cargo: {e}")
        return False

# ================== VIEWS ==================
class StatusPlanoView(View):
    def __init__(self, user_id, planos_ativos):
        super().__init__(timeout=None)  # Permanente
        self.user_id = user_id
        self.planos_ativos = planos_ativos
        self.expandido = False

    @discord.ui.button(label="👀 Ver Mais", style=discord.ButtonStyle.secondary)
    async def ver_mais(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Não é seu painel.", ephemeral=True)
            return
        
        self.expandido = True
        button.label = "📄 Ver Menos"
        button.emoji = "📄"
        
        embed = await self.gerar_embed_expandido()
        await interaction.response.edit_message(embed=embed, view=self)

    async def gerar_embed_expandido(self):
        """Gera embed com informações detalhadas"""
        db = load_planos_db()
        agora = int(time.time())
        
        embed = discord.Embed(
            title=f"📊 Histórico Completo - {interaction.user.display_name}",
            color=discord.Color.blue()
        )
        
        # Planos ativos
        if self.planos_ativos:
            texto_ativo = ""
            for plano in self.planos_ativos:
                dias_restantes = (plano.get("data_fim", 0) - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                data_inicio = datetime.fromtimestamp(plano.get("data_inicio", 0)).strftime("%d/%m/%Y")
                texto_ativo += f"🟢 **{plano['descricao']}** ({modalidade})\n"
                texto_ativo += f"   📅 Iniciado: {data_inicio}\n"
                texto_ativo += f"   ⏰ Restam: {dias_restantes} dias\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=texto_ativo, inline=False)
        
        # Histórico de cancelamentos
        cancelamentos = []
        for plano in db:
            if (plano["user_id"] == self.user_id and 
                plano.get("cancelado", False)):
                cancelamentos.append(plano)
        
        if cancelamentos:
            texto_cancelado = ""
            for plano in cancelamentos[-5:]:  # Últimos 5
                data_cancel = datetime.fromtimestamp(plano.get("data_cancelamento", 0)).strftime("%d/%m/%Y")
                taxa = plano.get("taxa_cancelamento", 0)
                modalidade = plano.get("modalidade", "mensal")
                texto_cancelado += f"🔴 **{plano['descricao']}** ({modalidade})\n"
                texto_cancelado += f"   📅 Cancelado: {data_cancel}\n"
                texto_cancelado += f"   💰 Taxa: {int(taxa*100)}%\n\n"
            
            embed.add_field(name="❌ Cancelamentos (últimos 5)", value=texto_cancelado, inline=False)
        
        return embed

    @discord.ui.button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
    async def cancelar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Não é seu painel.", ephemeral=True)
            return
        
        if not self.planos_ativos:
            await interaction.response.send_message("❌ Nenhum plano ativo para cancelar.", ephemeral=True)
            return
        
        view = CancelarPlanoView(self.planos_ativos)
        embed = discord.Embed(
            title="🗑️ Cancelar Plano",
            description="Escolha qual plano cancelar:",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🛒 Comprar Assinaturas", style=discord.ButtonStyle.success)
    async def comprar_assinaturas(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Redirecionar para comando !planos
        embed = discord.Embed(
            title="🛒 Comprar Assinaturas",
            description="Use o comando `!planos` para ver todas as opções disponíveis.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
class EscolherModalidadeView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Mensal", style=discord.ButtonStyle.green)
    async def modalidade_mensal(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="💰 Assinatura Mensal",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {self.plano['preco']:.2f}/mês",
            color=discord.Color.green()
        )
        embed.add_field(name="✅ Vantagens", value="• Cobrança automática todo mês\n• Cancelamento após 2 meses sem taxa", inline=False)
        
        view = EscolherPagamentoView(self.plano, "mensal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💎 Pagar 1 Vez (+50%)", style=discord.ButtonStyle.blurple)
    async def modalidade_unica(self, interaction: discord.Interaction, button: discord.ui.Button):
        preco_unico = self.plano['preco'] * 1.5
        embed = discord.Embed(
            title="💎 Pagamento Único",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {preco_unico:.2f} (única vez)",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="⚠️ Política de Cancelamento",
            value="• Antes de 2 meses: 100% de taxa\n• 2-6 meses: 35% de taxa\n• Após 6 meses: 15% de taxa",
            inline=False
        )
        
        view = EscolherPagamentoView(self.plano, "unico")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
class PagamentoViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=1800)
        self.plano = plano

    @discord.ui.button(label="💳 PIX/Cartão/Débito", style=discord.ButtonStyle.green, emoji="💰")
    async def abrir_checkout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento. Tente novamente em alguns minutos.", ephemeral=True)
                return
            
            payment_record = salvar_preferencia_pendente(preferencia, interaction.user.id, self.plano)
            
            if not payment_record:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="💳 Pagamento Criado!",
                description=f"**Plano:** {self.plano['descricao']}\n**Valor:** R$ {self.plano['preco']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="💰 Formas de Pagamento Disponíveis:",
                value="• PIX (aprovação instantânea)\n• Cartão de Crédito (até 12x)\n• Cartão de Débito",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            embed.add_field(name="⏰ Validade", value="30 minutos", inline=True)
            embed.add_field(name="🔍 Status", value="Aguardando pagamento", inline=True)
            
            embed.add_field(
                name="📋 Como pagar:",
                value="1. Clique no link acima\n2. Escolha: PIX, Cartão ou Débito\n3. Complete o pagamento\n4. Volte aqui e clique 'Verificar Pagamento'",
                inline=False
            )
            
            embed.set_footer(text=f"ID: {preferencia['id']} - Plano ativa após confirmação")
            
            verificar_view = VerificarPagamentoViewCompleta(preferencia["external_reference"], interaction.user.id, self.plano)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no checkout: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

class VerificarPagamentoViewCompleta(View):
    def __init__(self, external_reference, user_id, plano):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda. Se você acabou de pagar, aguarde alguns minutos.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado com sucesso!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor Pago", value=f"R$ {self.plano['preco']:.2f}", inline=True)
                embed.add_field(name="🎯 Tipo", value=self.plano['tipo'].capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
                payments_db = load_payments_db()
                for payment_id, payment_data in payments_db.items():
                    if payment_data.get("external_reference") == self.external_reference:
                        payment_data["status"] = "approved"
                        save_payments_db(payments_db)
                        break
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando. Aguarde alguns minutos e tente novamente.", ephemeral=True)
                
            elif pagamento["status"] == "rejected":
                embed = discord.Embed(
                    title="❌ Pagamento Rejeitado",
                    description="Seu pagamento foi rejeitado. Tente novamente ou use outro método.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}. Continue aguardando ou tente novamente.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)

class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        db = load_planos_db()
        agora = int(time.time())
        
        # Verificar plano ativo do mesmo tipo
        for plano_ativo in db:
            if (plano_ativo["user_id"] == user_id and 
                plano_ativo["tipo"] == self.plano["tipo"] and 
                plano_ativo.get("pago", False) and
                plano_ativo.get("data_fim", 0) > agora and
                not plano_ativo.get("cancelado", False)):
                await interaction.response.send_message(
                    f"❌ Você já possui um plano **{self.plano['tipo']}** ativo!", 
                    ephemeral=True
                )
                return
        
        # Mostrar opções de modalidade
        embed = discord.Embed(
            title="🛒 Escolha a Modalidade",
            description=f"**Plano:** {self.plano['descricao']}",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="💰 Mensal (Recorrente)",
            value=f"R$ {self.plano['preco']:.2f}/mês\n✅ Renovação automática\n✅ Cancelamento flexível",
            inline=True
        )
        embed.add_field(
            name="💎 Único (+50%)",
            value=f"R$ {self.plano['preco'] * 1.5:.2f}\n⚠️ Válido 1 mês\n⚠️ Taxa de cancelamento",
            inline=True
        )
        
        view = EscolherModalidadeView(self.plano)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        try:
            db = load_planos_db()
            agora = int(time.time())
            
            for plano_ativo in db:
                if (plano_ativo["user_id"] == user_id and 
                    plano_ativo["tipo"] == self.plano["tipo"] and 
                    plano_ativo.get("pago", False) and
                    plano_ativo.get("data_fim", 0) > agora):
                    await interaction.response.send_message(
                        f"❌ Você já possui um plano ativo do tipo **{self.plano['tipo']}**!", 
                        ephemeral=True
                    )
                    return
            
            embed = discord.Embed(
                title="💳 Finalizar Compra",
                description=f"**Plano:** {self.plano['descricao']}\n**💰 Valor:** R$ {self.plano['preco']:.2f}",
                color=discord.Color.blue()
            )
            
            info = f"**Tipo:** {self.plano['tipo'].capitalize()}\n"
            
            if self.plano["id_plano"] == 2:  # Vendedor Verde
                info += "📅 **Postagem:** Alternada (hoje não, amanhã sim)\n"
            elif self.plano["id_plano"] == 8:  # Comprador Verde
                info += "📅 **Postagem:** 2 posts a cada 2 dias\n"
            elif "dias_post" in self.plano:
                if self.plano["dias_post"] == 1:
                    info += "📅 **Postagem:** Diária\n"
                else:
                    info += f"📅 **Postagem:** A cada {self.plano['dias_post']} dias\n"
            
            if "tags" in self.plano:
                if self.plano["tags"] == "ilimitado":
                    info += "🏷️ **Destaques:** Ilimitados\n"
                elif "posts_necessarios" in self.plano:
                    info += f"🏷️ **Destaques:** {self.plano['tags']} a cada {self.plano['posts_necessarios']} posts\n"
                else:
                    info += f"🏷️ **Tags disponíveis:** {self.plano['tags']}\n"
            
            embed.add_field(name="ℹ️ Detalhes", value=info, inline=False)
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.add_field(name="💳 Formas de Pagamento", value="PIX, Cartão Crédito/Débito", inline=True)
            
            embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
            
            pagamento_view = PagamentoViewCompleta(self.plano)
            await interaction.response.send_message(embed=embed, view=pagamento_view, ephemeral=True)
        
        except Exception as e:
            print(f"Erro na compra: {e}")
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)

class SelecionarPlanoView(View):
    def __init__(self):
        super().__init__(timeout=300)
        
        options = []
        for plano in PLANOS:
            emoji = "🔴" if "Vermelho" in plano["descricao"] else "🟢" if "Verde" in plano["descricao"] else "🔵"
            
            # Descrição personalizada para cada plano
            desc = f"Tipo: {plano['tipo'].capitalize()}"
            if plano["id_plano"] == 2:  # Vendedor Verde
                desc += " - Alternado"
            elif plano["id_plano"] == 4:  # Destacar Vermelho  
                desc += " - Ilimitado"
            elif plano["id_plano"] == 8:  # Comprador Verde
                desc += " - 2 posts/2 dias"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} - R$ {plano['preco']:.2f}",
                value=str(plano["id_plano"]),
                emoji=emoji,
                description=desc
            ))
        
        self.select = discord.ui.Select(
            placeholder="Escolha um plano...",
            options=options[:25],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        plano = next((p for p in PLANOS if p["id_plano"] == selected_id), None)
        
        if plano:
            embed = discord.Embed(
                title=f"💰 {plano['descricao']}",
                description=f"**Preço:** R$ {plano['preco']:.2f}\n**Tipo:** {plano['tipo'].capitalize()}",
                color=discord.Color.green()
            )
            
            # Descrições específicas para cada plano
            if plano["id_plano"] == 2:  # Vendedor Verde
                embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
            elif plano["id_plano"] == 8:  # Comprador Verde
                embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
            elif "dias_post" in plano:
                if plano["dias_post"] == 1:
                    embed.add_field(name="📅 Postagem", value="Diária", inline=True)
                else:
                    embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
            
            if "tags" in plano:
                if plano["tags"] == "ilimitado":
                    embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
                elif "posts_necessarios" in plano:
                    embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
                else:
                    embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
            
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
            
            view = ComprarViewCompleta(plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ================== MONITORAMENTO DE MENSAGENS ==================
@bot.event
async def on_message(message):
    """Monitora mensagens para controlar posts e detectar tags de destaque"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)
    
    # Verificar se é um canal de postagem
    canal_nome = message.channel.name
    user_id = message.author.id
    
    # Post na rede (vendedores)
    if canal_nome == CHANNEL_CONFIG["rede"]:
        pode, resultado = pode_postar(user_id, "vendedor")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Verificar se tem tag de destaque
        tem_destaque = "💯Destaques" in message.content
        
        if tem_destaque:
            pode_destacar, resultado_destaque = pode_usar_destaque(user_id)
            if not pode_destacar:
                # Remover apenas a tag, não deletar a mensagem
                content_sem_tag = message.content.replace("💯Destaques", "").strip()
                await message.edit(content=content_sem_tag)
                await message.channel.send(
                    f"⚠️ {message.author.mention} {resultado_destaque} A tag foi removida do seu post.",
                    delete_after=15
                )
                tem_destaque = False
        
        # Registrar o post
        registrar_post(user_id, "vendedor", tem_destaque)
        
        # Mover para destaques se necessário
        if tem_destaque:
            await mover_para_destaques(message)
    
    # Post na recomendação (compradores)
    elif canal_nome == CHANNEL_CONFIG["recomendacao"]:
        pode, resultado = pode_postar(user_id, "comprador")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Compradores não podem usar tag de destaque
        if "💯Destaques" in message.content:
            content_sem_tag = message.content.replace("💯Destaques", "").strip()
            await message.edit(content=content_sem_tag)
            await message.channel.send(
                f"⚠️ {message.author.mention} A tag de destaque não é permitida neste canal.",
                delete_after=10
            )
        
        # Registrar o post
        registrar_post(user_id, "comprador", False)

# ================== VERIFICAÇÃO AUTOMÁTICA DE PAGAMENTOS ==================
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente a cada 5 minutos"""
    await bot.wait_until_ready()
    
    try:
        payments_db = load_payments_db()
        if not payments_db:
            return
        
        for payment_id, payment_data in payments_db.items():
            if payment_data["status"] == "pending":
                external_ref = payment_data.get("external_reference")
                if external_ref:
                    pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                    
                    if pagamento_atual and pagamento_atual["status"] == "approved":
                        user_id = payment_data["user_id"]
                        plano = payment_data["plano"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano)
                        
                        if plano_ativado:
                            user = bot.get_user(user_id)
                            if user:
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        
                                        try:
                                            embed = discord.Embed(
                                                title="✅ PAGAMENTO CONFIRMADO AUTOMATICAMENTE!",
                                                description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                color=discord.Color.green()
                                            )
                                            embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                            embed.add_field(name="💰 Valor", value=f"R$ {plano['preco']:.2f}", inline=True)
                                            
                                            await user.send(embed=embed)
                                        except discord.Forbidden:
                                            print(f"Não foi possível enviar DM para {user.display_name}")
                                        except Exception as e:
                                            print(f"Erro ao notificar usuário: {e}")
                                        break
                            
                            payments_db[payment_id]["status"] = "approved"
                            save_payments_db(payments_db)
                            
                            print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# ================== COMANDOS ==================
@bot.command(name="planos")
async def mostrar_planos(ctx):
    """Mostra todos os planos disponíveis"""
    try:
        embed = discord.Embed(
            title="💼 Planos Disponíveis",
            description="⚠️ **IMPORTANTE:** Planos só são ativados após confirmação do pagamento!\n\n🛒 Use o menu abaixo para escolher:",
            color=discord.Color.blue()
        )
        
        vendedor_info = ""
        comprador_info = ""
        destacar_info = ""
        
        for plano in PLANOS:
            preco = f"R$ {plano['preco']:.2f}"
            if plano["tipo"] == "vendedor":
                if plano["id_plano"] == 2:  # Verde
                    vendedor_info += f"• {plano['descricao']}: {preco} (alternado - hoje não, amanhã sim)\n"
                elif plano["dias_post"] == 1:
                    vendedor_info += f"• {plano['descricao']}: {preco} (diário)\n"
                else:
                    vendedor_info += f"• {plano['descricao']}: {preco} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "comprador":
                if plano["id_plano"] == 8:  # Verde
                    comprador_info += f"• {plano['descricao']}: {preco} (2 posts a cada 2 dias)\n"
                elif plano["dias_post"] == 1:
                    comprador_info += f"• {plano['descricao']}: {preco} (diário)\n"
                else:
                    comprador_info += f"• {plano['descricao']}: {preco} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "destacar":
                if plano["tags"] == "ilimitado":
                    destacar_info += f"• {plano['descricao']}: {preco} (destaques ilimitados)\n"
                elif "posts_necessarios" in plano:
                    destacar_info += f"• {plano['descricao']}: {preco} ({plano['tags']} destaque(s) a cada {plano['posts_necessarios']} posts)\n"
                else:
                    destacar_info += f"• {plano['descricao']}: {preco} ({plano['tags']} destaque(s))\n"
        
        if vendedor_info:
            embed.add_field(name="🛍️ Planos Vendedor", value=vendedor_info, inline=True)
        if comprador_info:
            embed.add_field(name="🛒 Planos Comprador", value=comprador_info, inline=True)
        if destacar_info:
            embed.add_field(name="⭐ Planos Destacar", value=destacar_info, inline=True)
        
        embed.add_field(
            name="📋 Informações dos Canais",
            value=f"• **Vendedores:** Postem na {CHANNEL_CONFIG['rede']}\n• **Compradores:** Postem na {CHANNEL_CONFIG['recomendacao']}\n• **Destaques:** Posts com 💯Destaques vão para {CHANNEL_CONFIG['destaques']}",
            inline=False
        )
        
        embed.add_field(
            name="💳 Formas de Pagamento",
            value="• PIX (aprovação instantânea)\n• Cartão de Crédito (até 12x)\n• Cartão de Débito",
            inline=False
        )
        
        view = SelecionarPlanoView()
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar planos: {e}")
        await ctx.send("❌ Erro ao carregar planos. Tente novamente.")

@bot.command(name="plano")
async def plano_individual(ctx, id_plano: int = None):
    """Comprar plano específico por ID: !plano 1, !plano 2, etc"""
    if id_plano is None:
        embed = discord.Embed(
            title="❓ Como usar",
            description="Use: `!plano <número>`\n\n**Exemplos:**\n• `!plano 1` - Vendedor Vermelho\n• `!plano 2` - Vendedor Verde\n• `!plano 3` - Vendedor Azul",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="📋 Lista de IDs",
            value="\n".join([f"`{p['id_plano']}` - {p['descricao']}" for p in PLANOS[:5]]) + f"\n\n*Use `!planos` para ver todos*",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    plano = next((p for p in PLANOS if p["id_plano"] == id_plano), None)
    if not plano:
        await ctx.send(f"❌ Plano {id_plano} não encontrado. Use `!planos` para ver todos os planos disponíveis.")
        return
    
    try:
        embed = discord.Embed(
            title=f"Plano {id_plano}: {plano['descricao']}",
            description=f"**Preço:** R$ {plano['preco']:.2f}\n**Tipo:** {plano['tipo'].capitalize()}",
            color=discord.Color.blue()
        )
        
        # Descrições específicas para cada plano
        if plano["id_plano"] == 2:  # Vendedor Verde
            embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
        elif plano["id_plano"] == 8:  # Comprador Verde
            embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
        elif "dias_post" in plano:
            if plano["dias_post"] == 1:
                embed.add_field(name="📅 Postagem", value="Diária", inline=True)
            else:
                embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
        
        if "tags" in plano:
            if plano["tags"] == "ilimitado":
                embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
            elif "posts_necessarios" in plano:
                embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
            else:
                embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
        
        embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
        embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
        
        view = ComprarViewCompleta(plano)
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar plano individual: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.")

@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        posts_db = load_posts_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_encontrados = False
        planos_ativos = []
        planos_expirados = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                planos_encontrados = True
                fim = plano.get("data_fim", agora)
                
                if agora > fim:
                    planos_expirados.append(plano)
                else:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                ativo_text += f"• **{plano['descricao']}**\n  📅 {dias_restantes} dias restantes\n  🎯 Tipo: {plano['tipo'].capitalize()}\n\n"
            
            embed.add_field(
                name="✅ Planos Ativos",
                value=ativo_text,
                inline=False
            )
        
        # Mostrar estatísticas de posts para planos de destaque
        user_posts = posts_db.get(str(user_id), {})
        if any(p["tipo"] == "destacar" for p in planos_ativos):
            posts_rede = user_posts.get("posts_rede", 0)
            destaques_usados = user_posts.get("destaques_usados", 0)
            
            embed.add_field(
                name="📊 Estatísticas de Destaque",
                value=f"• Posts na rede: {posts_rede}\n• Destaques usados: {destaques_usados}",
                inline=True
            )
        
        # Mostrar estatísticas de posts para comprador verde
        if any(p["id_plano"] == 8 for p in planos_ativos):  # Comprador Verde
            posts_periodo = user_posts.get("posts_periodo_comprador", {"count": 0})
            embed.add_field(
                name="📊 Posts no Período Atual",
                value=f"• Posts usados: {posts_periodo.get('count', 0)}/2",
                inline=True
            )
        
        if planos_expirados:
            expirado_text = ""
            for plano in planos_expirados[-3:]:
                expirado_text += f"• {plano['descricao']}\n"
            
            embed.add_field(
                name="❌ Planos Expirados (últimos 3)",
                value=expirado_text,
                inline=False
            )
        
        if not planos_encontrados:
            embed.description = "Nenhum plano ativo encontrado.\n\n🛍️ Use `!planos` para ver as opções disponíveis!"
            embed.color = discord.Color.orange()
        
        embed.add_field(
            name="📋 Comandos Úteis",
            value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!ajuda` - Todos os comandos",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status. Tente novamente.")

@bot.command(name="ajuda", aliases=["help"])
async def ajuda(ctx):
    """Comandos disponíveis"""
    embed = discord.Embed(
        title="🤖 Central de Ajuda - Discord Bot",
        description="Sistema completo de planos com pagamentos reais via Mercado Pago",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="🛍️ Comandos de Compra",
        value="• `!planos` - Ver todos os planos disponíveis\n• `!plano <id>` - Comprar plano específico (ex: `!plano 1`)\n• `!status` - Ver seus planos ativos",
        inline=False
    )
    
    embed.add_field(
        name="🌟 Sistema Privado",
        value="• `!assinatura` - Acessar seu espaço privado de assinatura\n• `!assinar` - Alias para o comando acima\n• `!privado` - Outro alias para privacidade",
        inline=False
    )
    
    embed.add_field(
        name="📋 Tipos de Planos ATUALIZADOS",
        value=f"• **Vendedor** - Para postar na {CHANNEL_CONFIG['rede']}\n  - Verde: Alternado (hoje não, amanhã sim)\n  - Vermelho: Diário\n  - Azul: A cada 2 dias\n• **Comprador** - Para postar na {CHANNEL_CONFIG['recomendacao']}\n  - Verde: 2 posts a cada 2 dias\n  - Vermelho: Diário\n  - Azul: A cada 2 dias\n• **Destacar** - Para usar a tag 💯Destaques\n  - Vermelho: Ilimitado\n  - Verde/Azul: Baseado em posts",
        inline=False
    )
    
    embed.add_field(
        name="🏷️ Sistema de Destaques",
        value=f"• Tag **💯Destaques** só funciona na {CHANNEL_CONFIG['rede']}\n• Posts destacados aparecem automaticamente no {CHANNEL_CONFIG['destaques']}\n• **Vermelho:** Ilimitado\n• **Verde:** 2 destaques a cada 10 posts\n• **Azul:** 1 destaque a cada 10 posts",
        inline=False
    )
    
    embed.add_field(
        name="🔒 Privacidade Garantida",
        value=f"• Use `!assinatura` para acessar seu espaço privado\n• Localizado na categoria **{CHANNEL_CONFIG['categoria_assinaturas']}**\n• Apenas você pode ver suas conversas\n• Todos os comandos funcionam no espaço privado",
        inline=False
    )
    
    embed.add_field(
        name="💳 Formas de Pagamento",
        value="• **PIX** - Aprovação instantânea\n• **Cartão de Crédito** - Até 12x sem juros\n• **Cartão de Débito** - Aprovação rápida",
        inline=True
    )
    
    embed.add_field(
        name="⚡ Processo de Compra",
        value="1. Use `!assinatura` para privacidade\n2. Escolha o plano com `!planos`\n3. Efetue o pagamento\n4. Aguarde confirmação automática\n5. Plano ativado!",
        inline=True
    )
    
    embed.add_field(
        name="⏰ Informações Importantes",
        value="• **Duração:** Todos os planos duram 30 dias\n• **Ativação:** Automática após pagamento confirmado\n• **Verificação:** Sistema verifica pagamentos a cada 5 minutos\n• **Cooldown:** Respeitado automaticamente conforme plano",
        inline=False
    )
    
    embed.set_footer(text="💡 Dica: Use !assinatura para começar com privacidade!")
    
    await ctx.send(embed=embed)

@bot.command(name="limpar", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def limpar_planos_expirados(ctx, confirmar: str = None):
    """Remove planos expirados do banco de dados (apenas administradores)"""
    if confirmar != "SIM":
        embed = discord.Embed(
            title="⚠️ Confirmação Necessária",
            description="Este comando irá remover TODOS os planos expirados do banco de dados.\n\nPara confirmar, use: `!limpar SIM`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        planos_ativos = []
        removidos = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos.append(plano)
            else:
                removidos += 1
        
        save_planos_db(planos_ativos)
        
        embed = discord.Embed(
            title="🧹 Limpeza Concluída",
            description=f"**{removidos}** planos expirados foram removidos.\n**{len(planos_ativos)}** planos ativos mantidos.",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro na limpeza: {e}")
        await ctx.send("❌ Erro ao limpar banco de dados.")

@bot.command(name="assinatura", aliases=["assinar", "privado"])
async def acessar_assinatura_privada(ctx):
    """Cria ou acessa seu espaço privado de assinatura"""
    try:
        # Configurar fórum se necessário
        forum_configurado = await garantir_forum_configurado(ctx.guild)
        if not forum_configurado:
            await ctx.send("❌ Erro ao configurar sistema de fórum. Contate um administrador.", delete_after=10)
            return
        
        # Obter ou criar thread privada
        thread_privada = await obter_ou_criar_thread_privada(ctx.author, ctx.guild)
        
        if not thread_privada:
            await ctx.send("❌ Erro ao criar/acessar seu espaço privado. Tente novamente.", delete_after=10)
            return
        
        # Resposta pública temporária
        embed = discord.Embed(
            title="✅ Espaço Privado Criado!",
            description=f"Seu espaço privado de assinatura foi criado!\n\n🔗 **Acesse:** {thread_privada.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🔒 Privacidade",
            value="• Apenas você pode ver e interagir\n• Comandos do bot funcionam normalmente\n• Totalmente confidencial",
            inline=False
        )
        embed.set_footer(text="Esta mensagem será deletada em 15 segundos")
        
        await ctx.send(embed=embed, delete_after=15)
        
        # Deletar comando do usuário por privacidade
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        
        # Mensagem de boas-vindas na thread privada
        if thread_privada.message_count <= 1:  # Se é nova thread
            welcome_embed = discord.Embed(
                title="🎉 Bem-vindo ao seu espaço privado!",
                description="Este é seu ambiente privado para gerenciar assinaturas e planos.",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(
                name="🛍️ Comandos Disponíveis:",
                value="• `!planos` - Ver planos disponíveis\n• `!status` - Seus planos ativos\n• `!plano <id>` - Comprar plano específico",
                inline=False
            )
            welcome_embed.add_field(
                name="🔒 Privacidade Garantida:",
                value="• Ninguém mais pode ver este chat\n• Seus dados estão seguros\n• Pagamentos processados com segurança",
                inline=False
            )
            
            await thread_privada.send(embed=welcome_embed)
        
    except Exception as e:
        print(f"Erro no comando assinatura: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.command(name="stats")
@commands.has_permissions(administrator=True)
async def estatisticas_bot(ctx):
    """Mostra estatísticas do bot (apenas administradores)"""
    try:
        db = load_planos_db()
        payments_db = load_payments_db()
        posts_db = load_posts_db()
        agora = int(time.time())
        
        planos_ativos = 0
        planos_expirados = 0
        total_arrecadado = 0
        pagamentos_pendentes = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos += 1
            else:
                planos_expirados += 1
        
        for payment_data in payments_db.values():
            if payment_data["status"] == "approved":
                total_arrecadado += payment_data.get("amount", 0)
            elif payment_data["status"] == "pending":
                pagamentos_pendentes += 1
        
        tipos = {"vendedor": 0, "comprador": 0, "destacar": 0}
        for plano in db:
            if plano.get("data_fim", 0) > agora:
                tipo = plano.get("tipo", "")
                if tipo in tipos:
                    tipos[tipo] += 1
        
        total_posts_rede = sum(user_data.get("posts_rede", 0) for user_data in posts_db.values())
        total_destaques = sum(user_data.get("destaques_usados", 0) for user_data in posts_db.values())
        
        embed = discord.Embed(
            title="📊 Estatísticas do Bot",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📈 Planos",
            value=f"**Ativos:** {planos_ativos}\n**Expirados:** {planos_expirados}\n**Total:** {planos_ativos + planos_expirados}",
            inline=True
        )
        
        embed.add_field(
            name="💰 Financeiro",
            value=f"**Arrecadado:** R$ {total_arrecadado:.2f}\n**Pendentes:** {pagamentos_pendentes}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Por Tipo (Ativos)",
            value=f"**Vendedor:** {tipos['vendedor']}\n**Comprador:** {tipos['comprador']}\n**Destacar:** {tipos['destacar']}",
            inline=True
        )
        
        embed.add_field(
            name="📊 Atividade",
            value=f"**Posts na rede:** {total_posts_rede}\n**Destaques usados:** {total_destaques}",
            inline=True
        )
        
        embed.add_field(
            name="🤖 Bot Info",
            value=f"**Servidores:** {len(bot.guilds)}\n**Usuários:** {len(set(bot.get_all_members()))}",
            inline=True
        )
        
        embed.set_footer(text=f"Última verificação: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro nas estatísticas: {e}")
        await ctx.send("❌ Erro ao gerar estatísticas.")

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} está online!")
    print(f"📊 Conectado a {len(bot.guilds)} servidor(s)")
    print(f"👥 Alcançando {len(set(bot.get_all_members()))} usuários únicos")
    print(f"💳 Mercado Pago integrado - Sistema de cobrança REAL ativo")
    print(f"⚠️  Planos só são ativados após confirmação de pagamento!")
    print(f"🏷️  Sistema de destaques integrado com canais: {CHANNEL_CONFIG}")
    print("🔄 PLANOS ATUALIZADOS:")
    print("   • Vendedor Verde: Alternado (hoje não, amanhã sim)")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Ilimitado")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
        print("🔄 Verificação automática de pagamentos iniciada (a cada 5 minutos)")

@bot.event
async def on_command_error(ctx, error):
    """Tratamento de erros dos comandos"""
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❓ Comando não encontrado",
            description=f"O comando `{ctx.message.content}` não existe.\n\nUse `!ajuda` para ver todos os comandos disponíveis.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumento inválido. Verifique o comando e tente novamente.", delete_after=5)
    
    else:
        print(f"Erro no comando {ctx.command}: {error}")
        await ctx.send("❌ Erro interno. Tente novamente mais tarde.", delete_after=5)

@bot.event
async def on_guild_join(guild):
    """Quando o bot entra em um servidor novo"""
    print(f"➕ Bot adicionado ao servidor: {guild.name} (ID: {guild.id})")
    
    # Configurar fórum automaticamente
    await garantir_forum_configurado(guild)
    
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="🎉 Obrigado por me adicionar!",
                description="Sou um bot de **venda de planos** com pagamentos reais via Mercado Pago!",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🚀 Como começar",
                value="• `!ajuda` - Ver todos os comandos\n• `!assinatura` - Acessar espaço privado\n• `!planos` - Ver planos disponíveis\n• `!status` - Verificar seus planos",
                inline=False
            )
            
            embed.add_field(
                name="🔒 Sistema Privado",
                value="• Use `!assinatura` para ter privacidade total\n• Cada usuário tem seu espaço individual\n• Ninguém pode ver suas conversas ou compras",
                inline=False
            )
            
            embed.add_field(
                name="💳 Sobre os Pagamentos",
                value="• Pagamentos **100% reais** via Mercado Pago\n• PIX, Cartão de Crédito e Débito\n• Ativação automática após confirmação",
                inline=False
            )
            
            embed.add_field(
                name="🏷️ Configuração dos Canais",
                value=f"• Crie o canal **{CHANNEL_CONFIG['rede']}** para vendedores\n• Crie o canal **{CHANNEL_CONFIG['recomendacao']}** para compradores\n• Crie o canal **{CHANNEL_CONFIG['destaques']}** para posts destacados\n• Categoria **{CHANNEL_CONFIG['categoria_assinaturas']}** criada automaticamente",
                inline=False
            )
            
            embed.add_field(
                name="🆕 PLANOS ATUALIZADOS",
                value="• **Vendedor Verde:** Alternado (hoje não, amanhã sim)\n• **Comprador Verde:** 2 posts a cada 2 dias\n• **Destacar Vermelho:** Destaques ilimitados",
                inline=False
            )
            
            embed.set_footer(text="Digite !assinatura para começar com total privacidade!")
            
            try:
                await channel.send(embed=embed)
                break
            except discord.Forbidden:
                continue

@bot.event
async def on_member_join(member):
    """Quando um usuário entra no servidor"""
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        for plano in db:
            if (plano["user_id"] == member.id and 
                plano.get("pago", False) and 
                plano.get("data_fim", 0) > agora):
                
                await assign_role_to_member(member, plano["tipo"])
                print(f"Cargo {plano['tipo']} reatribuído para {member.display_name}")
                
    except Exception as e:
        print(f"Erro ao reatribuir cargos para {member.display_name}: {e}")

# ================== INICIALIZAÇÃO ==================
if __name__ == "__main__":
    print("🚀 Iniciando Discord Bot...")
    print("💳 Sistema de cobrança REAL ativo via Mercado Pago")
    print("⚠️  IMPORTANTE: Planos só são ativados após confirmação de pagamento!")
    print("🔄 Verificação automática de pagamentos a cada 5 minutos")
    print(f"🏷️ Canais configurados: {CHANNEL_CONFIG}")
    print("🆕 ATUALIZAÇÕES DOS PLANOS:")
    print("   • Vendedor Verde: Sistema alternado")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Destaques ilimitados")
    print("=" * 60)
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if not ML_TOKEN:
        print("❌ ML_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if ML_TOKEN.startswith("APP_USR"):
        print("🚨 ATENÇÃO: Usando tokens de PRODUÇÃO - Cobranças serão REAIS!")
    elif ML_TOKEN.startswith("TEST"):
        print("🧪 Usando tokens de TESTE - Ambiente de desenvolvimento")
    else:
        print("⚠️  Token do Mercado Pago não identificado")
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ TOKEN do Discord inválido! Verifique o arquivo .env")
    except discord.HTTPException as e:
        print(f"❌ Erro HTTP: {e}")
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado pelo usuário")
    except Exception as e:
        print(f"❌ Erro inesperado ao iniciar bot: {e}")
    finally:
        print("🔴 Bot desconectado")
        # ================== MONITORAMENTO DE MENSAGENS ==================
@bot.event
async def on_message(message):
    """Monitora mensagens para controlar posts e detectar tags de destaque"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)
    
    # Verificar se é um canal de postagem
    canal_nome = message.channel.name
    user_id = message.author.id
    
    # Post na rede (vendedores)
    if canal_nome == CHANNEL_CONFIG["rede"]:
        pode, resultado = pode_postar(user_id, "vendedor")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Verificar se tem tag de destaque
        tem_destaque = "💯Destaques" in message.content
        
        if tem_destaque:
            pode_destacar, resultado_destaque = pode_usar_destaque(user_id)
            if not pode_destacar:
                content_sem_tag = message.content.replace("💯Destaques", "").strip()
                await message.edit(content=content_sem_tag)
                await message.channel.send(
                    f"⚠️ {message.author.mention} {resultado_destaque} A tag foi removida do seu post.",
                    delete_after=15
                )
                tem_destaque = False
        
        # Registrar o post
        registrar_post(user_id, "vendedor", tem_destaque)
        
        # Mover para destaques se necessário
        if tem_destaque:
            await mover_para_destaques(message)
    
    # Post na recomendação (compradores)
    elif canal_nome == CHANNEL_CONFIG["recomendacao"]:
        pode, resultado = pode_postar(user_id, "comprador")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Compradores não podem usar tag de destaque
        if "💯Destaques" in message.content:
            content_sem_tag = message.content.replace("💯Destaques", "").strip()
            await message.edit(content=content_sem_tag)
            await message.channel.send(
                f"⚠️ {message.author.mention} A tag de destaque não é permitida neste canal.",
                delete_after=10
            )
        
        # Registrar o post
        registrar_post(user_id, "comprador", False)

# ================== VERIFICAÇÃO AUTOMÁTICA DE PAGAMENTOS ==================
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente a cada 5 minutos"""
    await bot.wait_until_ready()
    
    try:
        # Verificar pagamentos de cartão
        payments_db = load_payments_db()
        if payments_db:
            for payment_id, payment_data in payments_db.items():
                if payment_data["status"] == "pending":
                    external_ref = payment_data.get("external_reference")
                    if external_ref:
                        pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                        
                        if pagamento_atual and pagamento_atual["status"] == "approved":
                            user_id = payment_data["user_id"]
                            plano = payment_data["plano"]
                            modalidade = external_ref.split("_")[-1] if "_" in external_ref else "mensal"
                            
                            plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                            
                            if plano_ativado:
                                user = bot.get_user(user_id)
                                if user:
                                    for guild in bot.guilds:
                                        member = guild.get_member(user_id)
                                        if member:
                                            await assign_role_to_member(member, plano["tipo"])
                                            
                                            try:
                                                embed = discord.Embed(
                                                    title="✅ PAGAMENTO CONFIRMADO AUTOMATICAMENTE!",
                                                    description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                    color=discord.Color.green()
                                                )
                                                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                                embed.add_field(name="🎯 Modalidade", value=modalidade.capitalize(), inline=True)
                                                
                                                await user.send(embed=embed)
                                            except discord.Forbidden:
                                                print(f"Não foi possível enviar DM para {user.display_name}")
                                            except Exception as e:
                                                print(f"Erro ao notificar usuário: {e}")
                                            break
                                
                                payments_db[payment_id]["status"] = "approved"
                                save_payments_db(payments_db)
                                
                                print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
        
        # Verificar pagamentos PIX
        pix_db = load_pix_db()
        if pix_db:
            for payment_id, pix_data in pix_db.items():
                if pix_data["status"] == "pending":
                    pagamento_pix = verificar_pagamento_pix(payment_id)
                    
                    if pagamento_pix and pagamento_pix["status"] == "approved":
                        user_id = pix_data["user_id"]
                        plano = pix_data["plano"]
                        modalidade = pix_data["modalidade"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                        
                        if plano_ativado:
                            user = bot.get_user(user_id)
                            if user:
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        
                                        try:
                                            embed = discord.Embed(
                                                title="✅ PIX CONFIRMADO AUTOMATICAMENTE!",
                                                description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                color=discord.Color.green()
                                            )
                                            embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                            embed.add_field(name="🎯 Modalidade", value=modalidade.capitalize(), inline=True)
                                            embed.add_field(name="💰 Valor", value=f"R$ {pix_data['amount']:.2f}", inline=True)
                                            
                                            await user.send(embed=embed)
                                        except discord.Forbidden:
                                            print(f"Não foi possível enviar DM para {user.display_name}")
                                        except Exception as e:
                                            print(f"Erro ao notificar usuário: {e}")
                                        break
                            
                            pix_db[payment_id]["status"] = "approved"
                            save_pix_db(pix_db)
                            
                            print(f"✅ Plano PIX {plano['descricao']} ativado automaticamente para usuário {user_id}")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# ================== COMANDOS ==================
@bot.command(name="planos")
async def mostrar_planos(ctx):
    """Mostra todos os planos disponíveis"""
    try:
        embed = discord.Embed(
            title="💼 Planos Disponíveis",
            description="🛍️ Escolha entre **Mensal** ou **Pagamento Único (+50%)**\n\n🛒 Use o menu abaixo para escolher:",
            color=discord.Color.blue()
        )
        
        vendedor_info = ""
        comprador_info = ""
        destacar_info = ""
        
        for plano in PLANOS:
            preco = f"R$ {plano['preco']:.2f}"
            preco_unico = f"R$ {plano['preco'] * 1.5:.2f}"
            
            if plano["tipo"] == "vendedor":
                if plano["id_plano"] == 2:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (alternado)\n"
                elif plano["dias_post"] == 1:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (diário)\n"
                else:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "comprador":
                if plano["id_plano"] == 8:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (2 posts/2 dias)\n"
                elif plano["dias_post"] == 1:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (diário)\n"
                else:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "destacar":
                if plano["tags"] == "ilimitado":
                    destacar_info += f"• {plano['descricao']}: {preco} | {preco_unico} (ilimitado)\n"
                elif "posts_necessarios" in plano:
                    destacar_info += f"• {plano['descricao']}: {preco} | {preco_unico} ({plano['tags']} a cada {plano['posts_necessarios']} posts)\n"
        
        if vendedor_info:
            embed.add_field(name="🛍️ Vendedor (Mensal | Único)", value=vendedor_info, inline=True)
        if comprador_info:
            embed.add_field(name="🛒 Comprador (Mensal | Único)", value=comprador_info, inline=True)
        if destacar_info:
            embed.add_field(name="⭐ Destacar (Mensal | Único)", value=destacar_info, inline=True)
        
        embed.add_field(
            name="💎 Pagamento Único",
            value="• 50% a mais no valor\n• Válido por 1 mês\n• Taxa de cancelamento antes de 2 meses: 100%",
            inline=False
        )
        
        embed.add_field(
            name="💳 Formas de Pagamento",
            value="• **PIX** - Confirmação rápida\n• **Cartão** - Crédito/Débito (até 12x)",
            inline=False
        )
        
        view = SelecionarPlanoView()
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar planos: {e}")
        await ctx.send("❌ Erro ao carregar planos. Tente novamente.")

@bot.command(name="plano")
async def plano_individual(ctx, id_plano: int = None):
    """Comprar plano específico por ID"""
    if id_plano is None:
        embed = discord.Embed(
            title="❓ Como usar",
            description="Use: `!plano <número>`\n\n**Exemplos:**\n• `!plano 1` - Vendedor Vermelho\n• `!plano 2` - Vendedor Verde",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="📋 Lista de IDs",
            value="\n".join([f"`{p['id_plano']}` - {p['descricao']}" for p in PLANOS[:5]]) + "\n\n*Use `!planos` para ver todos*",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    plano = next((p for p in PLANOS if p["id_plano"] == id_plano), None)
    if not plano:
        await ctx.send(f"❌ Plano {id_plano} não encontrado. Use `!planos` para ver todos os planos disponíveis.")
        return
    
    try:
        embed = discord.Embed(
            title=f"Plano {id_plano}: {plano['descricao']}",
            description=f"**Mensal:** R$ {plano['preco']:.2f}\n**Único:** R$ {plano['preco'] * 1.5:.2f} (+50%)\n**Tipo:** {plano['tipo'].capitalize()}",
            color=discord.Color.blue()
        )
        
        if plano["id_plano"] == 2:
            embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
        elif plano["id_plano"] == 8:
            embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
        elif "dias_post" in plano:
            if plano["dias_post"] == 1:
                embed.add_field(name="📅 Postagem", value="Diária", inline=True)
            else:
                embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
        
        if "tags" in plano:
            if plano["tags"] == "ilimitado":
                embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
            elif "posts_necessarios" in plano:
                embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
        
        embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
        
        view = ComprarViewCompleta(plano)
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar plano individual: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.")

@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        posts_db = load_posts_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_encontrados = False
        planos_ativos = []
        planos_expirados = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                planos_encontrados = True
                fim = plano.get("data_fim", agora)
                
                if agora > fim:
                    planos_expirados.append(plano)
                else:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                ativo_text += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n  🎯 Tipo: {plano['tipo'].capitalize()}\n\n"
            
            embed.add_field(
                name="✅ Planos Ativos",
                value=ativo_text,
                inline=False
            )
            
            # Botão para cancelar planos
            view = View(timeout=300)
            cancelar_btn = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Você não pode usar este botão.", ephemeral=True)
                    return
                
                agora = int(time.time())
                planos_cancelaveis = [p for p in planos_ativos if p.get("data_fim", 0) > agora]
                
                if not planos_cancelaveis:
                    await interaction.response.send_message("❌ Nenhum plano ativo para cancelar.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_cancelaveis)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha o plano que deseja cancelar:",
                    color=discord.Color.orange()
                )
                embed_cancelar.add_field(
                    name="⚠️ Política de Cancelamento:",
                    value="• Antes de 2 meses: Taxa de 100%\n• Após 2 meses: Sem taxa\n• Pagamento único: Sempre taxa de 100%",
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            cancelar_btn.callback = cancelar_callback
            view.add_item(cancelar_btn)
            
            embed.set_footer(text="Use o botão abaixo para cancelar um plano")
        else:
            view = None
        
        # Estatísticas de posts
        user_posts = posts_db.get(str(user_id), {})
        if any(p["tipo"] == "destacar" for p in planos_ativos):
            posts_rede = user_posts.get("posts_rede", 0)
            destaques_usados = user_posts.get("destaques_usados", 0)
            
            embed.add_field(
                name="📊 Estatísticas de Destaque",
                value=f"• Posts na rede: {posts_rede}\n• Destaques usados: {destaques_usados}",
                inline=True
            )
        
        if any(p["id_plano"] == 8 for p in planos_ativos):
            posts_periodo = user_posts.get("posts_periodo_comprador", {"count": 0})
            embed.add_field(
                name="📊 Posts no Período Atual",
                value=f"• Posts usados: {posts_periodo.get('count', 0)}/2",
                inline=True
            )
        
        if planos_expirados:
            expirado_text = ""
            for plano in planos_expirados[-3:]:
                modalidade = plano.get("modalidade", "mensal")
                expirado_text += f"• {plano['descricao']} ({modalidade})\n"
            
            embed.add_field(
                name="❌ Planos Expirados (últimos 3)",
                value=expirado_text,
                inline=False
            )
        
        if not planos_encontrados:
            embed.description = "Nenhum plano ativo encontrado.\n\n🛍️ Use `!planos` para ver as opções disponíveis!"
            embed.color = discord.Color.orange()
        
        embed.add_field(
            name="📋 Comandos Úteis",
            value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!ajuda` - Todos os comandos",
            inline=False
        )
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status. Tente novamente.")

@bot.command(name="ajuda", aliases=["help"])
async def ajuda(ctx):
    """Comandos disponíveis"""
    embed = discord.Embed(
        title="🤖 Central de Ajuda - Sistema de Assinaturas",
        description="Sistema completo com PIX, Cartão e Cancelamentos",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="🛍️ Comandos de Compra",
        value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!status` - Ver/cancelar seus planos",
        inline=False
    )
    
    embed.add_field(
        name="🌟 Sistema Privado",
        value="• `!assinatura` - Espaço privado de assinatura\n• `!assinar` - Alias para privacidade\n• `!privado` - Outro alias",
        inline=False
    )
    
    embed.add_field(
        name="💰 Modalidades de Pagamento",
        value="• **Mensal**: Preço normal, cancelamento flexível\n• **Único**: +50% do valor, válido 1 mês, taxa cancelamento\n• **PIX**: Confirmação rápida\n• **Cartão**: Crédito/Débito até 12x",
        inline=False
    )
    
    embed.add_field(
        name="🗑️ Sistema de Cancelamento",
        value="• Use `!status` e clique em 'Cancelar Plano'\n• Antes de 2 meses: Taxa de 100%\n• Após 2 meses: Sem taxa\n• Pagamento único: Sempre 100% de taxa",
        inline=False
    )
    
    embed.add_field(
        name="📋 Tipos de Planos",
        value="• **Vendedor Verde**: Alternado (hoje não, amanhã sim)\n• **Comprador Verde**: 2 posts a cada 2 dias\n• **Destacar Vermelho**: Destaques ilimitados",
        inline=False
    )
    
    embed.set_footer(text="💡 Use !assinatura para total privacidade!")
    
    await ctx.send(embed=embed)

@bot.command(name="limpar", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def limpar_planos_expirados(ctx, confirmar: str = None):
    """Remove planos expirados do banco de dados"""
    if confirmar != "SIM":
        embed = discord.Embed(
            title="⚠️ Confirmação Necessária",
            description="Este comando irá remover TODOS os planos expirados.\n\nPara confirmar: `!limpar SIM`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        planos_ativos = []
        removidos = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos.append(plano)
            else:
                removidos += 1
        
        save_planos_db(planos_ativos)
        
        embed = discord.Embed(
            title="🧹 Limpeza Concluída",
            description=f"**{removidos}** planos expirados removidos.\n**{len(planos_ativos)}** planos ativos mantidos.",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro na limpeza: {e}")
        await ctx.send("❌ Erro ao limpar banco de dados.")

@bot.command(name="assinatura", aliases=["assinar", "privado"])
async def acessar_assinatura_privada(ctx):
    """Cria ou acessa seu espaço privado de assinatura"""
    try:
        forum_configurado = await garantir_forum_configurado(ctx.guild)
        if not forum_configurado:
            await ctx.send("❌ Erro ao configurar sistema de fórum. Contate um administrador.", delete_after=10)
            return
        
        thread_privada = await obter_ou_criar_thread_privada(ctx.author, ctx.guild)
        
        if not thread_privada:
            await ctx.send("❌ Erro ao criar/acessar seu espaço privado. Tente novamente.", delete_after=10)
            return
        
        embed = discord.Embed(
            title="✅ Espaço Privado Criado!",
            description=f"Acesse: {thread_privada.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🔒 Privacidade Total",
            value="• Apenas você pode ver\n• PIX e Cartão disponíveis\n• Cancelamento via !status",
            inline=False
        )
        embed.set_footer(text="Mensagem deletada em 15s")
        
        await ctx.send(embed=embed, delete_after=15)
        
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        
        if thread_privada.message_count <= 1:
            welcome_embed = discord.Embed(
                title="🎉 Seu Espaço Privado!",
                description="Ambiente privado para gerenciar assinaturas.",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(
                name="🛍️ Comandos:",
                value="• `!planos` - Ver planos\n• `!status` - Gerenciar/cancelar\n• `!plano <id>` - Comprar específico",
                inline=False
            )
            welcome_embed.add_field(
                name="💳 Pagamentos:",
                value="• PIX - Confirmação rápida\n• Cartão - Até 12x sem juros\n• Modalidade única ou mensal",
                inline=False
            )
            
            await thread_privada.send(embed=welcome_embed)
        
    except Exception as e:
        print(f"Erro no comando assinatura: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.command(name="stats")
@commands.has_permissions(administrator=True)
async def estatisticas_bot(ctx):
    """Estatísticas do bot"""
    try:
        db = load_planos_db()
        payments_db = load_payments_db()
        pix_db = load_pix_db()
        posts_db = load_posts_db()
        agora = int(time.time())
        
        planos_ativos = 0
        planos_expirados = 0
        total_arrecadado_cartao = 0
        total_arrecadado_pix = 0
        pagamentos_pendentes = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos += 1
            else:
                planos_expirados += 1
        
        for payment_data in payments_db.values():
            if payment_data["status"] == "approved":
                total_arrecadado_cartao += payment_data.get("amount", 0)
            elif payment_data["status"] == "pending":
                pagamentos_pendentes += 1
        
        for pix_data in pix_db.values():
            if pix_data["status"] == "approved":
                total_arrecadado_pix += pix_data.get("amount", 0)
        
        tipos = {"vendedor": 0, "comprador": 0, "destacar": 0}
        modalidades = {"mensal": 0, "unico": 0}
        
        for plano in db:
            if plano.get("data_fim", 0) > agora:
                tipo = plano.get("tipo", "")
                modalidade = plano.get("modalidade", "mensal")
                if tipo in tipos:
                    tipos[tipo] += 1
                if modalidade in modalidades:
                    modalidades[modalidade] += 1
        
        total_posts_rede = sum(user_data.get("posts_rede", 0) for user_data in posts_db.values())
        total_destaques = sum(user_data.get("destaques_usados", 0) for user_data in posts_db.values())
        
        embed = discord.Embed(
            title="📊 Estatísticas do Sistema",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📈 Planos",
            value=f"**Ativos:** {planos_ativos}\n**Expirados:** {planos_expirados}",
            inline=True
        )
        
        total_arrecadado = total_arrecadado_cartao + total_arrecadado_pix
        embed.add_field(
            name="💰 Financeiro",
            value=f"**Total:** R$ {total_arrecadado:.2f}\n**Cartão:** R$ {total_arrecadado_cartao:.2f}\n**PIX:** R$ {total_arrecadado_pix:.2f}\n**Pendentes:** {pagamentos_pendentes}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Por Tipo",
            value=f"**Vendedor:** {tipos['vendedor']}\n**Comprador:** {tipos['comprador']}\n**Destacar:** {tipos['destacar']}",
            inline=True
        )
        
        embed.add_field(
            name="💎 Modalidades",
            value=f"**Mensal:** {modalidades['mensal']}\n**Único:** {modalidades['unico']}",
            inline=True
        )
        
        embed.add_field(
            name="📊 Atividade",
            value=f"**Posts rede:** {total_posts_rede}\n**Destaques:** {total_destaques}",
            inline=True
        )
        
        embed.add_field(
            name="🤖 Bot",
            value=f"**Servidores:** {len(bot.guilds)}\n**Usuários:** {len(set(bot.get_all_members()))}",
            inline=True
        )
        
        embed.set_footer(text=f"Última verificação: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro nas estatísticas: {e}")
        await ctx.send("❌ Erro ao gerar estatísticas.")

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} está online!")
    print(f"📊 Conectado a {len(bot.guilds)} servidor(s)")
    print(f"👥 Alcançando {len(set(bot.get_all_members()))} usuários únicos")
    print(f"💳 Sistema COMPLETO ativo:")
    print("   • Pagamentos PIX e Cartão")
    print("   • Modalidades: Mensal e Única (+50%)")
    print("   • Sistema de cancelamento com taxas")
    print("   • Verificação automática a cada 5min")
    print(f"🏷️ Canais: {CHANNEL_CONFIG}")
    print("🔄 FUNCIONALIDADES PRINCIPAIS:")
    print("   • PIX: Pagamento rápido via código")
    print("   • Cartão: Até 12x sem juros")  
    print("   • Cancelamento: Taxa 100% antes de 2 meses")
    print("   • Cargos: Vendedor/Comprador/Destacar")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
        print("🔄 Verificação automática iniciada")

@bot.event
async def on_command_error(ctx, error):
    """Tratamento de erros"""
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❓ Comando não encontrado",
            description=f"Use `!ajuda` para ver comandos disponíveis.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Sem permissão.", delete_after=5)
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumento inválido.", delete_after=5)
    
    else:
        print(f"Erro no comando {ctx.command}: {error}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.event
async def on_guild_join(guild):
    """Quando o bot entra em um servidor novo"""
    print(f"➕ Bot adicionado ao servidor: {guild.name} (ID: {guild.id})")
    
    # Configurar fórum automaticamente
    await garantir_forum_configurado(guild)
    
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="🎉 Sistema de Assinaturas Ativado!",
                description="Bot com pagamentos reais via PIX e Cartão!",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🚀 Começar",
                value="• `!ajuda` - Todos os comandos\n• `!assinatura` - Espaço privado\n• `!planos` - Ver planos disponíveis",
                inline=False
            )
            
            embed.add_field(
                name="💰 Novidades",
                value="• **PIX**: Pagamento instantâneo\n• **Modalidade Única**: +50% do valor, 1 mês\n• **Cancelamento**: Com sistema de taxas",
                inline=False
            )
            
            embed.add_field(
                name="🏷️ Configure os Canais",
                value=f"• `{CHANNEL_CONFIG['rede']}` - Para vendedores\n• `{CHANNEL_CONFIG['recomendacao']}` - Para compradores\n• `{CHANNEL_CONFIG['destaques']}` - Posts destacados",
                inline=False
            )
            
            embed.add_field(
                name="⚡ Sistema Automático",
                value="• Verificação de pagamentos a cada 5min\n• Cargos atribuídos automaticamente\n• Controle de posts por plano",
                inline=False
            )
            
            embed.set_footer(text="Digite !assinatura para começar com privacidade total!")
            
            try:
                await channel.send(embed=embed)
                break
            except discord.Forbidden:
                continue

@bot.event
async def on_member_join(member):
    """Quando um usuário entra no servidor - reatribuir cargos"""
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        for plano in db:
            if (plano["user_id"] == member.id and 
                plano.get("pago", False) and 
                plano.get("data_fim", 0) > agora):
                
                await assign_role_to_member(member, plano["tipo"])
                print(f"Cargo {plano['tipo']} reatribuído para {member.display_name}")
                
    except Exception as e:
        print(f"Erro ao reatribuir cargos para {member.display_name}: {e}")

# ================== INICIALIZAÇÃO ==================
if __name__ == "__main__":
    print("🚀 Iniciando Sistema de Assinaturas Discord...")
    print("=" * 60)
    print("💳 PAGAMENTOS REAIS VIA MERCADO PAGO")
    print("📱 PIX - Pagamento instantâneo")
    print("💳 CARTÃO - Crédito/Débito até 12x")
    print("💎 MODALIDADE ÚNICA - +50% do valor, válido 1 mês")
    print("🗑️ SISTEMA DE CANCELAMENTO - Taxa 100% antes de 2 meses")
    print("🤖 VERIFICAÇÃO AUTOMÁTICA - A cada 5 minutos")
    print("🎯 CARGOS AUTOMÁTICOS - Vendedor/Comprador/Destacar")
    print("=" * 60)
    print(f"🏷️ Canais configurados: {CHANNEL_CONFIG}")
    print("🆕 ATUALIZAÇÕES DOS PLANOS:")
    print("   • Vendedor Verde: Sistema alternado (hoje não, amanhã sim)")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Destaques ilimitados")
    print("=" * 60)
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if not ML_TOKEN:
        print("❌ ML_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if ML_TOKEN.startswith("APP_USR"):
        print("🚨 ATENÇÃO: TOKENS DE PRODUÇÃO - COBRANÇAS REAIS!")
        print("💰 PIX e Cartões serão cobrados de verdade!")
    elif ML_TOKEN.startswith("TEST"):
        print("🧪 TOKENS DE TESTE - Ambiente de desenvolvimento")
        print("🔧 Pagamentos simulados para testes")
    else:
        print("⚠️ Token do Mercado Pago não identificado")
    
    print("=" * 60)
    print("🔄 RECURSOS IMPLEMENTADOS:")
    print("✅ PIX com código QR")
    print("✅ Cartão até 12x sem juros")
    print("✅ Modalidade única (+50%)")
    print("✅ Sistema de cancelamento")
    print("✅ Verificação automática")
    print("✅ Cargos automáticos")
    print("✅ Controle de posts")
    print("✅ Sistema de destaques")
    print("✅ Espaço privado por usuário")
    print("=" * 60)
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ TOKEN do Discord inválido! Verifique o arquivo .env")
    except discord.HTTPException as e:
        print(f"❌ Erro HTTP: {e}")
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado pelo usuário")
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        print("🔴 Bot desconectado")
import os
import json
import time
import random
import asyncio
import requests
from typing import List, Dict, Any
from datetime import datetime, timedelta
import pytz

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from dotenv import load_dotenv
import mercadopago

# ----------------- CONFIGURAÇÕES -----------------
load_dotenv("arquivo.env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ML_TOKEN = os.getenv("ML_TOKEN")
ML_PUBLIC_KEY = os.getenv("ML_PUBLIC_KEY")

# Inicializar SDK do Mercado Pago
sdk = mercadopago.SDK(ML_TOKEN)

DB_FILE = "planos_ativos.json"
POST_DB = "posts.json"
PAYMENTS_DB = "pagamentos.json"
PIX_DB = "pix_payments.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------- PLANOS ATUALIZADOS COM MODALIDADES -----------------
PLANOS = [
    {"id_plano": 1, "descricao": "Vendedor Vermelho 🔴", "tipo": "vendedor", "dias_post": 1, "preco": 25.00},
    {"id_plano": 2, "descricao": "Vendedor Verde 🟢", "tipo": "vendedor", "dias_post": 1, "alternado": True, "preco": 15.90},
    {"id_plano": 3, "descricao": "Vendedor Azul 🔵", "tipo": "vendedor", "dias_post": 2, "preco": 7.90},
    {"id_plano": 4, "descricao": "Destacar Vermelho 🔴", "tipo": "destacar", "tags": "ilimitado", "preco": 75.00},
    {"id_plano": 5, "descricao": "Destacar Verde 🟢", "tipo": "destacar", "tags": 2, "posts_necessarios": 10, "preco": 27.80},
    {"id_plano": 6, "descricao": "Destacar Azul 🔵", "tipo": "destacar", "tags": 1, "posts_necessarios": 10, "preco": 17.80},
    {"id_plano": 7, "descricao": "Comprador Vermelho 🔴", "tipo": "comprador", "dias_post": 1, "preco": 24.90},
    {"id_plano": 8, "descricao": "Comprador Verde 🟢", "tipo": "comprador", "dias_post": 2, "posts_por_periodo": 2, "preco": 12.00},
    {"id_plano": 9, "descricao": "Comprador Azul 🔵", "tipo": "comprador", "dias_post": 2, "preco": 9.50},
]

# Configurações dos canais
CHANNEL_CONFIG = {
    "rede": "🛒rede",
    "recomendacao": "🌟recomendação-do-caveira",
    "destaques": "💯destaques",
    "forum_assinaturas": "assinar🌟",
    "categoria_assinaturas": "📃🌟Assinaturas"
}

# ================== UTILITÁRIOS JSON ==================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        print(f"Erro ao ler {path}, usando valores padrão")
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar {path}: {e}")

def load_planos_db():
    return load_json(DB_FILE, [])

def save_planos_db(data):
    save_json(DB_FILE, data)

def load_payments_db():
    return load_json(PAYMENTS_DB, {})

def save_payments_db(data):
    save_json(PAYMENTS_DB, data)

def load_posts_db():
    return load_json(POST_DB, {})

def save_posts_db(data):
    save_json(POST_DB, data)

def load_pix_db():
    return load_json(PIX_DB, {})

def save_pix_db(data):
    save_json(PIX_DB, data)

# ================== SISTEMA DE FÓRUM PRIVADO ==================
async def obter_ou_criar_thread_privada(user: discord.Member, guild: discord.Guild):
    """Obtém ou cria uma thread privada no fórum de assinaturas para o usuário"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} não encontrada")
            return None
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} não encontrado na categoria")
            return None
        
        if not isinstance(forum_channel, discord.ForumChannel):
            print(f"Canal {CHANNEL_CONFIG['forum_assinaturas']} não é um canal de fórum")
            return None
        
        for thread in forum_channel.threads:
            if thread.name == f"Assinatura - {user.display_name}" or thread.owner_id == user.id:
                return thread
        
        try:
            embed = discord.Embed(
                title=f"🌟 Assinatura Privada - {user.display_name}",
                description="Este é seu espaço privado de assinatura. Apenas você pode ver e interagir aqui.",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="📋 Como usar:",
                value="• Use `!status` para ver seus planos\n• Use `!planos` para comprar novos planos\n• Este chat é totalmente privado",
                inline=False
            )
            embed.set_footer(text="Sistema de Assinaturas Privadas")
            
            thread = await forum_channel.create_thread(
                name=f"Assinatura - {user.display_name}",
                content="",
                embed=embed,
                auto_archive_duration=10080,
                slowmode_delay=0
            )
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            await thread.thread.edit(overwrites=overwrites)
            await thread.thread.add_user(user)
            
            print(f"Thread privada criada para {user.display_name}")
            return thread.thread
            
        except discord.Forbidden:
            print(f"Sem permissão para criar thread no fórum")
            return None
        except Exception as e:
            print(f"Erro ao criar thread: {e}")
            return None
    
    except Exception as e:
        print(f"Erro no sistema de fórum privado: {e}")
        return None

async def garantir_forum_configurado(guild: discord.Guild):
    """Garante que o fórum e categoria estão configurados corretamente"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            try:
                categoria = await guild.create_category(CHANNEL_CONFIG["categoria_assinaturas"])
                print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} criada")
            except discord.Forbidden:
                print("Sem permissão para criar categoria")
                return False
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False
                    ),
                    guild.me: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        create_public_threads=True,
                        create_private_threads=True,
                        manage_threads=True
                    )
                }
                
                forum_channel = await categoria.create_forum(
                    CHANNEL_CONFIG["forum_assinaturas"],
                    topic="Fórum de assinaturas privadas - cada usuário tem seu espaço individual",
                    overwrites=overwrites,
                    slowmode_delay=60
                )
                print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} criado")
            except discord.Forbidden:
                print("Sem permissão para criar fórum")
                return False
            except Exception as e:
                print(f"Erro ao criar fórum: {e}")
                return False
        
        return True
    
    except Exception as e:
        print(f"Erro ao configurar fórum: {e}")
        return False

# ================== SISTEMA DE CANCELAMENTO ==================
def calcular_taxa_cancelamento(data_inicio: int, eh_pagamento_unico: bool = False):
    """Calcula a taxa de cancelamento baseada no tempo desde a compra"""
    agora = int(time.time())
    dias_desde_compra = (agora - data_inicio) // 86400
    
    if dias_desde_compra < 60:  # Menos de 2 meses
        if eh_pagamento_unico:
            return 1.0  # 100% de taxa para pagamento único
        else:
            return 1.0  # 100% de taxa para cancelamento antes de 2 meses
    else:
        return 0.0  # Sem taxa após 2 meses

def pode_cancelar_plano(user_id: int, id_plano: int):
    """Verifica se o usuário pode cancelar um plano específico"""
    db = load_planos_db()
    agora = int(time.time())
    
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["id_plano"] == id_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            
            return True, plano
    
    return False, None

# ================== SISTEMA PIX ==================
def gerar_chave_pix():
    """Gera uma chave PIX única para o pagamento"""
    import uuid
    return str(uuid.uuid4())

def criar_pagamento_pix(plano: dict, user_id: int, username: str, modalidade: str = "mensal"):
    """Cria um pagamento PIX através do Mercado Pago"""
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        # Calcular preço baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5  # 50% a mais
        
        referencia_pix = f"pix_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        payment_data = {
            "transaction_amount": preco_final,
            "description": f"Plano {plano['descricao']} - {modalidade.capitalize()}",
            "payment_method_id": "pix",
            "payer": {
                "email": f"user{user_id}@discord.bot",
                "first_name": nome_usuario,
                "last_name": "Discord",
                "identification": {
                    "type": "CPF",
                    "number": "00000000000"  # CPF fictício para teste
                }
            },
            "external_reference": referencia_pix,
            "notification_url": "https://webhook.site/unique-id",  # Substitua por sua URL de webhook
            "date_of_expiration": (agora + timedelta(minutes=30)).isoformat()
        }
        
        payment_response = sdk.payment().create(payment_data)
        
        if payment_response["status"] == 201:
            payment_info = payment_response["response"]
            
            # Salvar informações do PIX
            pix_db = load_pix_db()
            pix_record = {
                "payment_id": payment_info["id"],
                "user_id": user_id,
                "plano": plano,
                "modalidade": modalidade,
                "amount": preco_final,
                "status": "pending",
                "created_date": payment_info["date_created"],
                "external_reference": referencia_pix,
                "qr_code": payment_info["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": payment_info["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "ticket_url": payment_info["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
            
            pix_db[str(payment_info["id"])] = pix_record
            save_pix_db(pix_db)
            
            return payment_info, pix_record
        else:
            print(f"Erro ao criar pagamento PIX: {payment_response}")
            return None, None
            
    except Exception as e:
        print(f"Erro ao criar pagamento PIX: {e}")
        return None, None

def verificar_pagamento_pix(payment_id: str):
    """Verifica o status de um pagamento PIX"""
    try:
        payment_response = sdk.payment().get(payment_id)
        
        if payment_response["status"] == 200:
            return payment_response["response"]
        else:
            print(f"Erro ao verificar pagamento PIX: {payment_response}")
            return None
            
    except Exception as e:
        print(f"Erro ao verificar pagamento PIX: {e}")
        return None

# ================== SISTEMA DE POSTS ATUALIZADO ==================
def pode_postar(user_id: int, tipo_plano: str):
    """Verifica se o usuário pode postar baseado no plano dele"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo
    plano_ativo = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == tipo_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_ativo = plano
            break
    
    if not plano_ativo:
        return False, "Você não possui um plano ativo do tipo necessário."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_ativo["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    user_posts = posts_db.get(str(user_id), {})
    ultimo_post = user_posts.get(f"ultimo_post_{tipo_plano}", 0)
    
    # VENDEDOR VERDE: Sistema alternado (hoje não, amanhã sim)
    if plano_info["id_plano"] == 2:  # Vendedor Verde
        if ultimo_post == 0:  # Primeiro post
            return True, plano_ativo
            
        dias_desde_ultimo = (agora - ultimo_post) // 86400
        if dias_desde_ultimo == 0:  # Mesmo dia do último post
            return False, "Você pode postar novamente amanhã (sistema alternado)."
        elif dias_desde_ultimo >= 1:  # 1+ dias depois - pode postar
            return True, plano_ativo
    
    # COMPRADOR VERDE: 2 posts a cada 2 dias
    elif plano_info["id_plano"] == 8:  # Comprador Verde
        posts_por_periodo = plano_info.get("posts_por_periodo", 2)
        periodo = plano_info.get("dias_post", 2) * 86400  # 2 dias em segundos
        
        posts_no_periodo = user_posts.get(f"posts_periodo_{tipo_plano}", {"inicio": 0, "count": 0})
        
        # Se passou o período, resetar contador
        if agora - posts_no_periodo["inicio"] >= periodo:
            posts_no_periodo = {"inicio": agora, "count": 0}
            user_posts[f"posts_periodo_{tipo_plano}"] = posts_no_periodo
            save_posts_db(posts_db)
        
        # Verificar se ainda pode postar no período atual
        if posts_no_periodo["count"] >= posts_por_periodo:
            tempo_restante = periodo - (agora - posts_no_periodo["inicio"])
            horas_restantes = tempo_restante // 3600
            return False, f"Você já fez {posts_por_periodo} posts neste período. Aguarde {horas_restantes} horas."
        
        return True, plano_ativo
    
    # OUTROS PLANOS: Sistema normal por dias
    else:
        dias_necessarios = plano_info.get("dias_post", 1)
        tempo_espera = dias_necessarios * 86400  # dias em segundos
        
        if agora - ultimo_post < tempo_espera:
            horas_restantes = (tempo_espera - (agora - ultimo_post)) // 3600
            return False, f"Você pode postar novamente em {horas_restantes} horas."
        
        return True, plano_ativo

def pode_usar_destaque(user_id: int):
    """Verifica se o usuário pode usar a tag de destaque"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo de destacar
    plano_destacar = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == "destacar" and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_destacar = plano
            break
    
    if not plano_destacar:
        return False, "Você precisa de um plano de destaque para usar esta tag."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_destacar["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    # PLANO VERMELHO: ILIMITADO
    if plano_info["id_plano"] == 4:  # Destacar Vermelho
        return True, plano_destacar
    
    user_posts = posts_db.get(str(user_id), {})
    
    # Para planos Verde e Azul de destaque, verificar posts na rede
    if "posts_necessarios" in plano_info:
        posts_rede = user_posts.get("posts_rede", 0)
        destaques_usados = user_posts.get("destaques_usados", 0)
        
        # Calcular quantos destaques pode usar
        destaques_disponiveis = (posts_rede // plano_info["posts_necessarios"]) * plano_info["tags"]
        
        if destaques_usados >= destaques_disponiveis:
            posts_faltantes = plano_info["posts_necessarios"] - (posts_rede % plano_info["posts_necessarios"])
            return False, f"Você precisa fazer mais {posts_faltantes} posts na 🛒rede para usar destaque novamente."
    
    return True, plano_destacar

def registrar_post(user_id: int, canal_tipo: str, tem_destaque: bool = False):
    """Registra um post do usuário"""
    posts_db = load_posts_db()
    user_posts = posts_db.get(str(user_id), {})
    agora = int(time.time())
    
    # Registrar último post por tipo
    if canal_tipo == "vendedor":
        user_posts["ultimo_post_vendedor"] = agora
        user_posts["posts_rede"] = user_posts.get("posts_rede", 0) + 1
    elif canal_tipo == "comprador":
        user_posts["ultimo_post_comprador"] = agora
        
        # Para comprador verde, atualizar contador do período
        db = load_planos_db()
        for plano in db:
            if (plano["user_id"] == user_id and 
                plano["tipo"] == "comprador" and 
                plano.get("pago", False) and
                plano.get("data_fim", 0) > agora):
                
                plano_info = next((p for p in PLANOS if p["id_plano"] == plano["id_plano"]), None)
                if plano_info and plano_info["id_plano"] == 8:  # Comprador Verde
                    posts_no_periodo = user_posts.get("posts_periodo_comprador", {"inicio": 0, "count": 0})
                    posts_no_periodo["count"] += 1
                    user_posts["posts_periodo_comprador"] = posts_no_periodo
                break
    
    # Registrar uso de destaque
    if tem_destaque:
        user_posts["destaques_usados"] = user_posts.get("destaques_usados", 0) + 1
    
    posts_db[str(user_id)] = user_posts
    save_posts_db(posts_db)

async def mover_para_destaques(message: discord.Message):
    """Move uma mensagem com tag de destaque para o canal de destaques"""
    try:
        guild = message.guild
        canal_destaques = discord.utils.get(guild.channels, name=CHANNEL_CONFIG["destaques"])
        
        if not canal_destaques:
            print(f"Canal {CHANNEL_CONFIG['destaques']} não encontrado")
            return
        
        embed = discord.Embed(
            title="💯 Post em Destaque",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.set_footer(text=f"Original em #{message.channel.name}")
        embed.timestamp = message.created_at
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        
        await canal_destaques.send(embed=embed)
        print(f"Post de {message.author.display_name} movido para destaques")
        
    except Exception as e:
        print(f"Erro ao mover para destaques: {e}")

# ================== MERCADO PAGO CARTÃO ==================
def criar_preferencia_pagamento(plano: dict, user_id: int, username: str, modalidade: str = "mensal"):
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        # Calcular preço baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5  # 50% a mais
        
        referencia = f"plano_{plano['id_plano']}_user_{user_id}_{int(time.time())}_{modalidade}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        preference_data = {
            "items": [
                {
                    "title": f"Plano {plano['descricao']} - {modalidade.capitalize()}",
                    "quantity": 1,
                    "unit_price": preco_final,
                    "currency_id": "BRL",
                    "description": f"Plano {plano['tipo']} - Discord Bot - {modalidade}"
                }
            ],
            "payer": {
                "name": nome_usuario,
                "surname": "Discord User"
            },
            "payment_methods": {
                "excluded_payment_methods": [],
                "excluded_payment_types": [],
                "installments": 12
            },
            "back_urls": {
                "success": "https://www.cleitodiscord.com/success",
                "failure": "https://www.cleitodiscord.com/failure", 
                "pending": "https://www.cleitodiscord.com/pending"
            },
            "auto_return": "approved",
            "external_reference": referencia,
            "statement_descriptor": "DISCORD_BOT",
            "expires": True,
            "expiration_date_from": agora.isoformat(),
            "expiration_date_to": (agora + timedelta(hours=24)).isoformat()
        }
        
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response["status"] == 201:
            return preference_response["response"]
        else:
            print(f"Erro ao criar preferência: {preference_response}")
            return None
    except Exception as e:
        print(f"Erro ao criar preferência de pagamento: {e}")
        return None

def verificar_pagamento_por_referencia(external_reference):
    try:
        filters = {"external_reference": external_reference}
        search_response = sdk.payment().search(filters)
        
        if search_response["status"] == 200:
            results = search_response["response"]["results"]
            if results:
                return results[0]
        elif search_response["status"] == 429:
            print("Rate limit atingido - aguardando...")
            time.sleep(5)
            return None
        else:
            print(f"Erro na busca de pagamento: {search_response}")
        return None
    except Exception as e:
        print(f"Erro ao buscar pagamento: {e}")
        return None

def ativar_plano_apos_pagamento(user_id: int, plano: dict, modalidade: str = "mensal"):
    try:
        db = load_planos_db()
        
        timestamp = int(time.time())
        
        # Definir duração baseada na modalidade
        if modalidade == "unico":
            duracao = 30 * 86400  # 30 dias para pagamento único
        else:
            duracao = 30 * 86400  # 30 dias para mensal (seria recorrente em produção)
        
        plano_registro = {
            "user_id": user_id,
            "id_plano": plano["id_plano"],
            "descricao": plano["descricao"],
            "tipo": plano["tipo"],
            "pago": True,
            "modalidade": modalidade,
            "data_inicio": timestamp,
            "data_fim": timestamp + duracao
        }
        
        db.append(plano_registro)
        save_planos_db(db)
        return plano_registro
    except Exception as e:
        print(f"Erro ao ativar plano: {e}")
        return None

# ================== ROLES DISCORD ==================
async def ensure_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        try:
            role = await guild.create_role(name=name, color=discord.Color.blue())
            print(f"Cargo '{name}' criado no servidor {guild.name}")
        except discord.Forbidden:
            print(f"Sem permissão para criar cargo: {name}")
            return None
        except Exception as e:
            print(f"Erro ao criar cargo {name}: {e}")
            return None
    return role

async def assign_role_to_member(member: discord.Member, tipo: str):
    try:
        role_name = tipo.capitalize()
        role = await ensure_role(member.guild, role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
            print(f"Cargo '{role_name}' atribuído a {member.display_name}")
            return True
        return True
    except discord.Forbidden:
        print(f"Sem permissão para adicionar cargo a {member.display_name}")
        return False
    except Exception as e:
        print(f"Erro ao atribuir cargo: {e}")
        return False


class EscolherPagamentoView(View):
    def __init__(self, plano, modalidade):
        super().__init__(timeout=300)
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="💳 Cartão/Débito", style=discord.ButtonStyle.primary)
    async def pagamento_cartao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento. Tente novamente em alguns minutos.", ephemeral=True)
                return
            
            preco_final = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
            
            embed = discord.Embed(
                title="💳 Pagamento com Cartão",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {preco_final:.2f}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="💰 Formas de Pagamento Disponíveis:",
                value="• Cartão de Crédito (até 12x)\n• Cartão de Débito",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            embed.set_footer(text=f"ID: {preferencia['id']} - Válido por 24h")
            
            verificar_view = VerificarPagamentoView(preferencia["external_reference"], interaction.user.id, self.plano, self.modalidade)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento cartão: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

    @discord.ui.button(label="📱 PIX", style=discord.ButtonStyle.success)
    async def pagamento_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            payment_info, pix_record = criar_pagamento_pix(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not payment_info or not pix_record:
                await interaction.followup.send("❌ Erro ao criar pagamento PIX. Tente novamente.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📱 Pagamento PIX",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {pix_record['amount']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="📋 Como Pagar:",
                value="1. Copie o código PIX abaixo\n2. Cole no seu app bancário\n3. Confirme o pagamento\n4. Clique em 'Verificar Pagamento'",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Código PIX:",
                value=f"```{pix_record['qr_code']}```",
                inline=False
            )
            
            embed.add_field(name="⏰ Validade", value="30 minutos", inline=True)
            embed.add_field(name="🔍 Status", value="Aguardando pagamento", inline=True)
            
            embed.set_footer(text=f"Payment ID: {payment_info['id']}")
            
            verificar_view = VerificarPagamentoPIXView(str(payment_info['id']), interaction.user.id, self.plano, self.modalidade)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento PIX: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

class VerificarPagamentoView(View):
    def __init__(self, external_reference, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda. Se você acabou de pagar, aguarde alguns minutos.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                preco_pago = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado com sucesso!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor Pago", value=f"R$ {preco_pago:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando. Aguarde alguns minutos e tente novamente.", ephemeral=True)
                
            elif pagamento["status"] == "rejected":
                embed = discord.Embed(
                    title="❌ Pagamento Rejeitado",
                    description="Seu pagamento foi rejeitado. Tente novamente ou use outro método.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}. Continue aguardando ou tente novamente.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)

class VerificarPagamentoPIXView(View):
    def __init__(self, payment_id, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.payment_id = payment_id
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar PIX", style=discord.ButtonStyle.secondary)
    async def verificar_pix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_pix(self.payment_id)
            
            if not pagamento:
                await interaction.followup.send("⏳ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                # Atualizar status no banco PIX
                pix_db = load_pix_db()
                if self.payment_id in pix_db:
                    pix_db[self.payment_id]["status"] = "approved"
                    save_pix_db(pix_db)
                
                embed = discord.Embed(
                    title="✅ PIX CONFIRMADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor", value=f"R$ {pix_db[self.payment_id]['amount']:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ PIX ainda não confirmado. Aguarde alguns minutos após o pagamento.", ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status PIX: {pagamento['status']}. Continue aguardando.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar PIX: {e}")
            await interaction.followup.send("❌ Erro ao verificar PIX. Tente novamente.", ephemeral=True)

class CancelarPlanoView(View):
    def __init__(self, planos_ativos):
        super().__init__(timeout=300)
        self.planos_ativos = planos_ativos
        
        options = []
        for i, plano in enumerate(planos_ativos):
            modalidade = plano.get("modalidade", "mensal")
            dias_restantes = (plano.get("data_fim", 0) - int(time.time())) // 86400
            
            taxa = calcular_taxa_cancelamento(plano.get("data_inicio", 0), modalidade == "unico")
            taxa_texto = f"Taxa: {int(taxa*100)}%" if taxa > 0 else "Sem taxa"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} ({modalidade})",
                value=str(i),
                description=f"{dias_restantes} dias restantes - {taxa_texto}",
                emoji="🔴" if taxa > 0 else "🟢"
            ))
        
        if options:
            self.select = discord.ui.Select(
                placeholder="Escolha o plano para cancelar...",
                options=options[:25],
                min_values=1,
                max_values=1
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_index = int(self.select.values[0])
        plano_selecionado = self.planos_ativos[selected_index]
        
        modalidade = plano_selecionado.get("modalidade", "mensal")
        taxa = calcular_taxa_cancelamento(plano_selecionado.get("data_inicio", 0), modalidade == "unico")
        dias_desde_compra = (int(time.time()) - plano_selecionado.get("data_inicio", 0)) // 86400
        
        embed = discord.Embed(
            title="⚠️ Confirmação de Cancelamento",
            description=f"**Plano:** {plano_selecionado['descricao']}\n**Modalidade:** {modalidade.capitalize()}",
            color=discord.Color.orange()
        )
        
        if taxa > 0:
            embed.add_field(
                name="💰 Taxa de Cancelamento",
                value=f"**{int(taxa*100)}%** do valor pago\n*Comprado há {dias_desde_compra} dias*",
                inline=False
            )
            embed.add_field(
                name="📋 Motivo da Taxa:",
                value="• Cancelamento antes de 2 meses" + (" (Pagamento único)" if modalidade == "unico" else ""),
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Sem Taxa",
                value="Cancelamento após 2 meses da compra",
                inline=False
            )
        
        embed.add_field(
            name="⚠️ ATENÇÃO:",
            value="• Plano será cancelado imediatamente\n• Acesso será removido\n• Não há reembolso além da taxa",
            inline=False
        )
        
        view = ConfirmarCancelamentoView(plano_selecionado)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmarCancelamentoView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="✅ Confirmar Cancelamento", style=discord.ButtonStyle.danger)
    async def confirmar_cancelamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            db = load_planos_db()
            
            # Remover o plano do banco de dados
            db = [p for p in db if not (p["user_id"] == self.plano["user_id"] and p["id_plano"] == self.plano["id_plano"])]
            save_planos_db(db)
            
            # Remover cargo do usuário
            guild_member = interaction.guild.get_member(self.plano["user_id"])
            if guild_member:
                role_name = self.plano["tipo"].capitalize()
                role = discord.utils.get(guild_member.guild.roles, name=role_name)
                if role and role in guild_member.roles:
                    await guild_member.remove_roles(role)
            
            modalidade = self.plano.get("modalidade", "mensal")
            taxa = calcular_taxa_cancelamento(self.plano.get("data_inicio", 0), modalidade == "unico")
            
            embed = discord.Embed(
                title="✅ Plano Cancelado",
                description=f"Seu plano **{self.plano['descricao']}** foi cancelado com sucesso.",
                color=discord.Color.red()
            )
            
            if taxa > 0:
                embed.add_field(
                    name="💰 Taxa Aplicada",
                    value=f"{int(taxa*100)}% conforme política de cancelamento",
                    inline=False
                )
            
            embed.add_field(
                name="📋 Informações:",
                value="• Acesso removido imediatamente\n• Cargo Discord removido\n• Para reativar, faça uma nova compra",
                inline=False
            )
            
            for item in self.children:
                item.disabled = True
            
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            
        except Exception as e:
            print(f"Erro ao cancelar plano: {e}")
            await interaction.response.send_message("❌ Erro ao cancelar plano. Tente novamente.", ephemeral=True)

    @discord.ui.button(label="❌ Manter Plano", style=discord.ButtonStyle.secondary)
    async def manter_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ Cancelamento Abortado",
            description="Seu plano foi mantido e continua ativo.",
            color=discord.Color.green()
        )
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        try:
            db = load_planos_db()
            agora = int(time.time())
            
            for plano_ativo in db:
                if (plano_ativo["user_id"] == user_id and 
                    plano_ativo["tipo"] == self.plano["tipo"] and 
                    plano_ativo.get("pago", False) and
                    plano_ativo.get("data_fim", 0) > agora):
                    await interaction.response.send_message(
                        f"❌ Você já possui um plano ativo do tipo **{self.plano['tipo']}**!", 
                        ephemeral=True
                    )
                    return
            
            embed = discord.Embed(
                title="🛍️ Escolha a Modalidade",
                description=f"**Plano:** {self.plano['descricao']}\n**Tipo:** {self.plano['tipo'].capitalize()}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="💰 Mensal",
                value=f"R$ {self.plano['preco']:.2f}/mês\n✅ Cancelamento flexível",
                inline=True
            )
            
            embed.add_field(
                name="💎 Pagar 1 Vez",
                value=f"R$ {self.plano['preco'] * 1.5:.2f} (+50%)\n⚠️ Taxa de cancelamento",
                inline=True
            )
            
            view = EscolherModalidadeView(self.plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        except Exception as e:
            print(f"Erro na compra: {e}")
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)

class SelecionarPlanoView(View):
    def __init__(self):
        super().__init__(timeout=300)
        
        options = []
        for plano in PLANOS:
            emoji = "🔴" if "Vermelho" in plano["descricao"] else "🟢" if "Verde" in plano["descricao"] else "🔵"
            
            desc = f"Tipo: {plano['tipo'].capitalize()}"
            if plano["id_plano"] == 2:
                desc += " - Alternado"
            elif plano["id_plano"] == 4:
                desc += " - Ilimitado"
            elif plano["id_plano"] == 8:
                desc += " - 2 posts/2 dias"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} - R$ {plano['preco']:.2f}",
                value=str(plano["id_plano"]),
                emoji=emoji,
                description=desc
            ))
        
        self.select = discord.ui.Select(
            placeholder="Escolha um plano...",
            options=options[:25],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        plano = next((p for p in PLANOS if p["id_plano"] == selected_id), None)
        
        if plano:
            embed = discord.Embed(
                title=f"💰 {plano['descricao']}",
                description=f"**Preço:** R$ {plano['preco']:.2f} (mensal)\n**Tipo:** {plano['tipo'].capitalize()}",
                color=discord.Color.green()
            )
            
            if plano["id_plano"] == 2:
                embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
            elif plano["id_plano"] == 8:
                embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
            elif "dias_post" in plano:
                if plano["dias_post"] == 1:
                    embed.add_field(name="📅 Postagem", value="Diária", inline=True)
                else:
                    embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
            
            if "tags" in plano:
                if plano["tags"] == "ilimitado":
                    embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
                elif "posts_necessarios" in plano:
                    embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
                else:
                    embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
            
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.set_footer(text="Escolha entre modalidade mensal ou pagamento único")
            
            view = ComprarViewCompleta(plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ================== CORREÇÕES - ADICIONAR ESTAS FUNÇÕES ==================

# 1. CORRIGIR FUNÇÃO DE CARGOS - SUBSTITUIR A EXISTENTE
async def assign_role_to_member(member: discord.Member, tipo: str):
    """VERSÃO CORRIGIDA - USA CARGOS EXISTENTES"""
    try:
        role_name = tipo.capitalize()  # vendedor -> Vendedor
        
        # BUSCAR cargo existente no servidor
        role = discord.utils.get(member.guild.roles, name=role_name)
        
        if not role:
            print(f"❌ Cargo '{role_name}' não encontrado no servidor")
            return False
        
        if role not in member.roles:
            await member.add_roles(role)
            print(f"✅ Cargo '{role_name}' atribuído a {member.display_name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao atribuir cargo: {e}")
        return False

# 2. NOVA VIEW PARA MODALIDADES (CORRIGIR BOTÃO "PAGAR 1 VEZ")
# ================== CORREÇÕES PRINCIPAIS ==================

# 1. ERRO NO BOTÃO "PAGAR 1 VEZ" - Typo no ephemeral
class EscolherModalidadeView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Mensal", style=discord.ButtonStyle.green)
    async def modalidade_mensal(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=f"💰 Plano Mensal",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {self.plano['preco']:.2f}/mês",
            color=discord.Color.green()
        )
        embed.add_field(name="✅ Vantagens", value="• Cancelamento após 2 meses sem taxa", inline=False)
        
        view = EscolherPagamentoView(self.plano, "mensal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💎 Pagar 1 Vez (+50%)", style=discord.ButtonStyle.blurple)
    async def modalidade_unica(self, interaction: discord.Interaction, button: discord.ui.Button):
        preco_unico = self.plano['preco'] * 1.5
        embed = discord.Embed(
            title=f"💎 Pagamento Único",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {preco_unico:.2f} (única vez)",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="⚠️ Taxa de Cancelamento",
            value="• Antes de 2 meses: **100% de taxa**\n• Válido por 30 dias",
            inline=False
        )
        
        view = EscolherPagamentoView(self.plano, "unico")
        # ERRO ESTAVA AQUI: ephemeal -> ephemeral
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 2. FUNÇÃO DE SALVAR PAGAMENTO CARTÃO CORRIGIDA
def salvar_preferencia_pendente(preference_data, user_id, plano, modalidade="mensal"):
    try:
        payments_db = load_payments_db()
        
        # Calcular preço final baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5
        
        payment_record = {
            "preference_id": preference_data["id"],
            "user_id": user_id,
            "plano": plano,
            "modalidade": modalidade,  # ADICIONAR modalidade
            "amount": preco_final,     # USAR preço correto
            "status": "pending",
            "created_date": preference_data["date_created"],
            "checkout_link": preference_data["init_point"],
            "external_reference": preference_data.get("external_reference")
        }
        
        payments_db[str(preference_data["id"])] = payment_record
        save_payments_db(payments_db)
        return payment_record
    except Exception as e:
        print(f"Erro ao salvar preferência pendente: {e}")
        return None

# 3. VIEW DE PAGAMENTO CORRIGIDA
class EscolherPagamentoView(View):
    def __init__(self, plano, modalidade):
        super().__init__(timeout=300)
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="💳 Cartão/Débito", style=discord.ButtonStyle.primary)
    async def pagamento_cartao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento.", ephemeral=True)
                return
            
            # SALVAR COM MODALIDADE
            payment_record = salvar_preferencia_pendente(preferencia, interaction.user.id, self.plano, self.modalidade)
            
            preco_final = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
            
            embed = discord.Embed(
                title="💳 Pagamento com Cartão",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {preco_final:.2f}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            verificar_view = VerificarPagamentoView(preferencia["external_reference"], interaction.user.id, self.plano, self.modalidade)
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento cartão: {e}")
            await interaction.followup.send("❌ Erro interno.", ephemeral=True)

    @discord.ui.button(label="📱 PIX", style=discord.ButtonStyle.success)
    async def pagamento_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            payment_info, pix_record = criar_pagamento_pix(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not payment_info or not pix_record:
                await interaction.followup.send("❌ Erro ao criar pagamento PIX.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📱 Pagamento PIX",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {pix_record['amount']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🔗 Código PIX:",
                value=f"```{pix_record['qr_code']}```",
                inline=False
            )
            
            verificar_view = VerificarPagamentoPIXView(str(payment_info['id']), interaction.user.id, self.plano, self.modalidade)
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento PIX: {e}")
            await interaction.followup.send("❌ Erro interno PIX.", ephemeral=True)

# 4. VERIFICAÇÃO DE PAGAMENTO CORRIGIDA
class VerificarPagamentoView(View):
    def __init__(self, external_reference, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                # ATUALIZAR STATUS NO BANCO
                payments_db = load_payments_db()
                for payment_id, payment_data in payments_db.items():
                    if payment_data.get("external_reference") == self.external_reference:
                        payment_data["status"] = "approved"
                        save_payments_db(payments_db)
                        break
                
                preco_pago = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado!",
                    color=discord.Color.green()
                )
                embed.add_field(name="💰 Valor", value=f"R$ {preco_pago:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando.", ephemeral=True)
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento.", ephemeral=True)

# 5. SISTEMA DE CANCELAMENTO CORRIGIDO
class CancelarPlanoView(View):
    def __init__(self, planos_ativos):
        super().__init__(timeout=300)
        self.planos_ativos = planos_ativos
        
        if not planos_ativos:
            return
        
        options = []
        for i, plano in enumerate(planos_ativos):
            modalidade = plano.get("modalidade", "mensal")
            dias_restantes = (plano.get("data_fim", 0) - int(time.time())) // 86400
            
            taxa = calcular_taxa_cancelamento(plano.get("data_inicio", 0), modalidade == "unico")
            taxa_texto = f"Taxa: {int(taxa*100)}%" if taxa > 0 else "Sem taxa"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} ({modalidade})",
                value=str(i),
                description=f"{dias_restantes} dias - {taxa_texto}",
                emoji="🔴" if taxa > 0 else "🟢"
            ))
        
        if options:
            self.select = discord.ui.Select(
                placeholder="Escolha o plano para cancelar...",
                options=options[:25]
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        try:
            selected_index = int(self.select.values[0])
            plano_selecionado = self.planos_ativos[selected_index]
            
            modalidade = plano_selecionado.get("modalidade", "mensal")
            taxa = calcular_taxa_cancelamento(plano_selecionado.get("data_inicio", 0), modalidade == "unico")
            
            embed = discord.Embed(
                title="⚠️ Confirmação de Cancelamento",
                description=f"**Plano:** {plano_selecionado['descricao']}\n**Modalidade:** {modalidade.capitalize()}",
                color=discord.Color.orange()
            )
            
            if taxa > 0:
                embed.add_field(
                    name="💰 Taxa de Cancelamento",
                    value=f"**{int(taxa*100)}%** do valor pago",
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Sem Taxa",
                    value="Cancelamento após 2 meses da compra",
                    inline=False
                )
            
            view = ConfirmarCancelamentoView(plano_selecionado)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no select callback: {e}")
            await interaction.response.send_message("❌ Erro ao processar seleção.", ephemeral=True)

class ConfirmarCancelamentoView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="✅ Confirmar Cancelamento", style=discord.ButtonStyle.danger)
    async def confirmar_cancelamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            db = load_planos_db()
            
            # REMOVER PLANO CORRETAMENTE
            db_filtrado = []
            plano_removido = False
            
            for p in db:
                if (p["user_id"] == self.plano["user_id"] and 
                    p["id_plano"] == self.plano["id_plano"] and
                    p.get("data_inicio") == self.plano.get("data_inicio")):
                    plano_removido = True
                    continue
                db_filtrado.append(p)
            
            if not plano_removido:
                await interaction.response.send_message("❌ Plano não encontrado.", ephemeral=True)
                return
            
            save_planos_db(db_filtrado)
            
            # REMOVER CARGO
            guild_member = interaction.guild.get_member(self.plano["user_id"])
            if guild_member:
                role_name = self.plano["tipo"].capitalize()
                role = discord.utils.get(guild_member.guild.roles, name=role_name)
                if role and role in guild_member.roles:
                    await guild_member.remove_roles(role)
            
            embed = discord.Embed(
                title="✅ Plano Cancelado",
                description=f"Seu plano **{self.plano['descricao']}** foi cancelado.",
                color=discord.Color.red()
            )
            
            for item in self.children:
                item.disabled = True
            
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            
        except Exception as e:
            print(f"Erro ao cancelar plano: {e}")
            await interaction.response.send_message("❌ Erro ao cancelar plano.", ephemeral=True)

    @discord.ui.button(label="❌ Manter Plano", style=discord.ButtonStyle.secondary)
    async def manter_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ Cancelamento Abortado",
            description="Seu plano foi mantido e continua ativo.",
            color=discord.Color.green()
        )
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

# 6. VERIFICAÇÃO AUTOMÁTICA CORRIGIDA
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente"""
    await bot.wait_until_ready()
    
    try:
        # Verificar pagamentos de cartão
        payments_db = load_payments_db()
        if payments_db:
            for payment_id, payment_data in payments_db.items():
                if payment_data["status"] == "pending":
                    external_ref = payment_data.get("external_reference")
                    if external_ref:
                        pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                        
                        if pagamento_atual and pagamento_atual["status"] == "approved":
                            user_id = payment_data["user_id"]
                            plano = payment_data["plano"]
                            modalidade = payment_data.get("modalidade", "mensal")  # PEGAR MODALIDADE
                            
                            plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                            
                            if plano_ativado:
                                # NOTIFICAR USUÁRIO E ATRIBUIR CARGO
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        break
                                
                                payments_db[payment_id]["status"] = "approved"
                                save_payments_db(payments_db)
                                
                                print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
        
        # Verificar pagamentos PIX
        pix_db = load_pix_db()
        if pix_db:
            for payment_id, pix_data in pix_db.items():
                if pix_data["status"] == "pending":
                    pagamento_pix = verificar_pagamento_pix(payment_id)
                    
                    if pagamento_pix and pagamento_pix["status"] == "approved":
                        user_id = pix_data["user_id"]
                        plano = pix_data["plano"]
                        modalidade = pix_data["modalidade"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                        
                        if plano_ativado:
                            for guild in bot.guilds:
                                member = guild.get_member(user_id)
                                if member:
                                    await assign_role_to_member(member, plano["tipo"])
                                    break
                            
                            pix_db[payment_id]["status"] = "approved"
                            save_pix_db(pix_db)
                            
                            print(f"✅ Plano PIX {plano['descricao']} ativado automaticamente")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# 7. COMANDO STATUS COM CANCELAMENTO
@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário com opção de cancelamento"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_ativos = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                fim = plano.get("data_fim", agora)
                if fim > agora:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                ativo_text += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=ativo_text, inline=False)
            
            # BOTÃO DE CANCELAMENTO
            view = View(timeout=300)
            cancelar_btn = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Você não pode usar este botão.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_ativos)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha o plano que deseja cancelar:",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            cancelar_btn.callback = cancelar_callback
            view.add_item(cancelar_btn)
        else:
            embed.description = "Nenhum plano ativo encontrado."
            view = None
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status.")

# 3. CORRIGIR VIEW DE COMPRA PARA MOSTRAR MODALIDADES
class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        db = load_planos_db()
        agora = int(time.time())
        
        # Verificar se já tem plano ativo do mesmo tipo
        for plano_ativo in db:
            if (plano_ativo["user_id"] == user_id and 
                plano_ativo["tipo"] == self.plano["tipo"] and 
                plano_ativo.get("pago", False) and
                plano_ativo.get("data_fim", 0) > agora):
                await interaction.response.send_message(
                    f"❌ Você já possui um plano **{self.plano['tipo']}** ativo!", 
                    ephemeral=True
                )
                return
        
        # Mostrar opções de modalidade
        embed = discord.Embed(
            title="🛍️ Escolha a Modalidade",
            description=f"**Plano:** {self.plano['descricao']}",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="💰 Mensal",
            value=f"R$ {self.plano['preco']:.2f}/mês",
            inline=True
        )
        embed.add_field(
            name="💎 Única (+50%)",
            value=f"R$ {self.plano['preco'] * 1.5:.2f}",
            inline=True
        )
        
        view = EscolherModalidadeView(self.plano)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 4. STATUS AUTOMÁTICO EM CANAL ESPECÍFICO
async def enviar_status_automatico(guild: discord.Guild):
    """Envia status em canal específico automaticamente"""
    try:
        canal_status = discord.utils.get(guild.channels, name="status-de-plano")
        
        if not canal_status:
            print("Canal 'status-de-plano' não encontrado")
            return
        
        # Limpar mensagens antigas
        try:
            async for message in canal_status.history(limit=100):
                if message.author == bot.user:
                    await message.delete()
        except:
            pass
        
        db = load_planos_db()
        agora = int(time.time())
        
        embed = discord.Embed(
            title="📊 Status Geral de Planos",
            description="Atualizações automáticas dos planos ativos",
            color=discord.Color.blue()
        )
        
        planos_ativos = 0
        usuarios_ativos = set()
        
        for plano in db:
            if plano.get("pago", False) and plano.get("data_fim", 0) > agora:
                planos_ativos += 1
                usuarios_ativos.add(plano["user_id"])
        
        embed.add_field(name="📈 Planos Ativos", value=str(planos_ativos), inline=True)
        embed.add_field(name="👥 Usuários com Plano", value=str(len(usuarios_ativos)), inline=True)
        embed.add_field(name="🔄 Última Atualização", value="Agora", inline=True)
        
        embed.set_footer(text="Use !status para ver seus planos individuais")
        
        await canal_status.send(embed=embed)
        
    except Exception as e:
        print(f"Erro no status automático: {e}")

# 5. COMANDO STATUS INTEGRADO
@bot.command(name="status")
async def status_integrado(ctx):
    """Status com integração ao canal específico"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        
        embed = discord.Embed(
            title=f"📊 Seus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_ativos = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                fim = plano.get("data_fim", agora)
                if fim > agora:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            texto_planos = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                texto_planos += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=texto_planos, inline=False)
            
            # Botão cancelar só se tem planos
            view = View(timeout=300)
            btn_cancelar = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Não é seu plano.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_ativos)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha qual plano cancelar:",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            btn_cancelar.callback = cancelar_callback
            view.add_item(btn_cancelar)
        else:
            embed.description = "Nenhum plano ativo."
            view = None
        
        # Tentar enviar no canal status-de-plano também
        try:
            canal_status = discord.utils.get(ctx.guild.channels, name="status-de-plano")
            if canal_status:
                embed_canal = embed.copy()
                embed_canal.set_footer(text=f"Status solicitado por {ctx.author.display_name}")
                await canal_status.send(embed=embed_canal)
        except:
            pass
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        await ctx.send("❌ Erro ao verificar status.")

# 6. TASK PARA ATUALIZAR STATUS AUTOMÁTICO
@tasks.loop(hours=6)  # Atualiza a cada 6 horas
async def atualizar_status_automatico():
    """Atualiza status no canal auimport os

import json
import time
import random
import asyncio
import requests
from typing import List, Dict, Any
from datetime import datetime, timedelta
import pytz

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from dotenv import load_dotenv
import mercadopago
import importlib
import importlib.util
import os

# ----------------- CONFIGURAÇÕES -----------------
load_dotenv("arquivo.env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ML_TOKEN = os.getenv("ML_TOKEN")
ML_PUBLIC_KEY = os.getenv("ML_PUBLIC_KEY")

# Inicializar SDK do Mercado Pago
sdk = mercadopago.SDK(ML_TOKEN)

DB_FILE = "planos_ativos.json"
POST_DB = "posts.json"
PAYMENTS_DB = "pagamentos.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------- PLANOS ATUALIZADOS CONFORME SOLICITADO -----------------
PLANOS = [
    {"id_plano": 1, "descricao": "Vendedor Vermelho 🔴", "tipo": "vendedor", "dias_post": 1, "preco": 25.00},
    {"id_plano": 2, "descricao": "Vendedor Verde 🟢", "tipo": "vendedor", "dias_post": 1, "alternado": True, "preco": 15.90},
    {"id_plano": 3, "descricao": "Vendedor Azul 🔵", "tipo": "vendedor", "dias_post": 2, "preco": 7.90},
    {"id_plano": 4, "descricao": "Destacar Vermelho 🔴", "tipo": "destacar", "tags": "ilimitado", "preco": 75.00},
    {"id_plano": 5, "descricao": "Destacar Verde 🟢", "tipo": "destacar", "tags": 2, "posts_necessarios": 10, "preco": 27.80},
    {"id_plano": 6, "descricao": "Destacar Azul 🔵", "tipo": "destacar", "tags": 1, "posts_necessarios": 10, "preco": 17.80},
    {"id_plano": 7, "descricao": "Comprador Vermelho 🔴", "tipo": "comprador", "dias_post": 1, "preco": 24.90},
    {"id_plano": 8, "descricao": "Comprador Verde 🟢", "tipo": "comprador", "dias_post": 2, "posts_por_periodo": 2, "preco": 12.00},
    {"id_plano": 9, "descricao": "Comprador Azul 🔵", "tipo": "comprador", "dias_post": 2, "preco": 9.50},
]

# Configurações dos canais
CHANNEL_CONFIG = {
    "rede": "🛒rede",
    "recomendacao": "🌟recomendação-do-caveira",
    "destaques": "💯destaques",
    "forum_assinaturas": "assinar🌟",
    "categoria_assinaturas": "📃🌟Assinaturas"
}

# ================== UTILITÁRIOS JSON ==================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        print(f"Erro ao ler {path}, usando valores padrão")
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar {path}: {e}")

def load_planos_db():
    return load_json(DB_FILE, [])

def save_planos_db(data):
    save_json(DB_FILE, data)

def load_payments_db():
    return load_json(PAYMENTS_DB, {})

def save_payments_db(data):
    save_json(PAYMENTS_DB, data)

def load_posts_db():
    return load_json(POST_DB, {})

def save_posts_db(data):
    save_json(POST_DB, data)

# ================== SISTEMA DE FÓRUM PRIVADO ==================
async def obter_ou_criar_thread_privada(user: discord.Member, guild: discord.Guild):
    "Obtém ou cria uma thread privada no fórum de assinaturas para o usuário"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} não encontrada")
            return None
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} não encontrado na categoria")
            return None
        
        if not isinstance(forum_channel, discord.ForumChannel):
            print(f"Canal {CHANNEL_CONFIG['forum_assinaturas']} não é um canal de fórum")
            return None
        
        for thread in forum_channel.threads:
            if thread.name == f"Assinatura - {user.display_name}" or thread.owner_id == user.id:
                return thread
        
        try:
            embed = discord.Embed(
                title=f"🌟 Assinatura Privada - {user.display_name}",
                description="Este é seu espaço privado de assinatura. Apenas você pode ver e interagir aqui.",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="📋 Como usar:",
                value="• Use `!status` para ver seus planos\n• Use `!planos` para comprar novos planos\n• Este chat é totalmente privado",
                inline=False
            )
            embed.set_footer(text="Sistema de Assinaturas Privadas")
            
            thread = await forum_channel.create_thread(
                name=f"Assinatura - {user.display_name}",
                content="",
                embed=embed,
                auto_archive_duration=10080,
                slowmode_delay=0
            )
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            await thread.thread.edit(overwrites=overwrites)
            await thread.thread.add_user(user)
            
            print(f"Thread privada criada para {user.display_name}")
            return thread.thread
            
        except discord.Forbidden:
            print(f"Sem permissão para criar thread no fórum")
            return None
        except Exception as e:
            print(f"Erro ao criar thread: {e}")
            return None
    
    except Exception as e:
        print(f"Erro no sistema de fórum privado: {e}")
        return None

async def garantir_forum_configurado(guild: discord.Guild):
    """Garante que o fórum e categoria estão configurados corretamente"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            try:
                categoria = await guild.create_category(CHANNEL_CONFIG["categoria_assinaturas"])
                print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} criada")
            except discord.Forbidden:
                print("Sem permissão para criar categoria")
                return False
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False
                    ),
                    guild.me: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        create_public_threads=True,
                        create_private_threads=True,
                        manage_threads=True
                    )
                }
                
                forum_channel = await categoria.create_forum(
                    CHANNEL_CONFIG["forum_assinaturas"],
                    topic="Fórum de assinaturas privadas - cada usuário tem seu espaço individual",
                    overwrites=overwrites,
                    slowmode_delay=60
                )
                print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} criado")
            except discord.Forbidden:
                print("Sem permissão para criar fórum")
                return False
            except Exception as e:
                print(f"Erro ao criar fórum: {e}")
                return False
        
        return True
    
    except Exception as e:
        print(f"Erro ao configurar fórum: {e}")
        return False

def pode_postar(user_id: int, tipo_plano: str):
    """Verifica se o usuário pode postar baseado no plano dele - VERSÃO ATUALIZADA"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo
    plano_ativo = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == tipo_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_ativo = plano
            break
    
    if not plano_ativo:
        return False, "Você não possui um plano ativo do tipo necessário."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_ativo["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    user_posts = posts_db.get(str(user_id), {})
    ultimo_post = user_posts.get(f"ultimo_post_{tipo_plano}", 0)
    
    # VENDEDOR VERDE: Sistema alternado (hoje não, amanhã sim)
    if plano_info["id_plano"] == 2:  # Vendedor Verde
        if ultimo_post == 0:  # Primeiro post
            return True, plano_ativo
            
        dias_desde_ultimo = (agora - ultimo_post) // 86400
        if dias_desde_ultimo == 0:  # Mesmo dia do último post
            return False, "Você pode postar novamente amanhã (sistema alternado)."
        elif dias_desde_ultimo >= 1:  # 1+ dias depois - pode postar
            return True, plano_ativo
    
    # COMPRADOR VERDE: 2 posts a cada 2 dias
    elif plano_info["id_plano"] == 8:  # Comprador Verde
        posts_por_periodo = plano_info.get("posts_por_periodo", 2)
        periodo = plano_info.get("dias_post", 2) * 86400  # 2 dias em segundos
        
        posts_no_periodo = user_posts.get(f"posts_periodo_{tipo_plano}", {"inicio": 0, "count": 0})
        
        # Se passou o período, resetar contador
        if agora - posts_no_periodo["inicio"] >= periodo:
            posts_no_periodo = {"inicio": agora, "count": 0}
            user_posts[f"posts_periodo_{tipo_plano}"] = posts_no_periodo
            save_posts_db(posts_db)
        
        # Verificar se ainda pode postar no período atual
        if posts_no_periodo["count"] >= posts_por_periodo:
            tempo_restante = periodo - (agora - posts_no_periodo["inicio"])
            horas_restantes = tempo_restante // 3600
            return False, f"Você já fez {posts_por_periodo} posts neste período. Aguarde {horas_restantes} horas."
        
        return True, plano_ativo
    
    # OUTROS PLANOS: Sistema normal por dias
    else:
        dias_necessarios = plano_info.get("dias_post", 1)
        tempo_espera = dias_necessarios * 86400  # dias em segundos
        
        if agora - ultimo_post < tempo_espera:
            horas_restantes = (tempo_espera - (agora - ultimo_post)) // 3600
            return False, f"Você pode postar novamente em {horas_restantes} horas."
        
        return True, plano_ativo

def pode_usar_destaque(user_id: int):
    """Verifica se o usuário pode usar a tag de destaque - VERSÃO ATUALIZADA"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo de destacar
    plano_destacar = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == "destacar" and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_destacar = plano
            break
    
    if not plano_destacar:
        return False, "Você precisa de um plano de destaque para usar esta tag."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_destacar["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    # PLANO VERMELHO: ILIMITADO
    if plano_info["id_plano"] == 4:  # Destacar Vermelho
        return True, plano_destacar
    
    user_posts = posts_db.get(str(user_id), {})
    
    # Para planos Verde e Azul de destaque, verificar posts na rede
    if "posts_necessarios" in plano_info:
        posts_rede = user_posts.get("posts_rede", 0)
        destaques_usados = user_posts.get("destaques_usados", 0)
        
        # Calcular quantos destaques pode usar
        destaques_disponiveis = (posts_rede // plano_info["posts_necessarios"]) * plano_info["tags"]
        
        if destaques_usados >= destaques_disponiveis:
            posts_faltantes = plano_info["posts_necessarios"] - (posts_rede % plano_info["posts_necessarios"])
            return False, f"Você precisa fazer mais {posts_faltantes} posts na 🛒rede para usar destaque novamente."
    
    return True, plano_destacar

def registrar_post(user_id: int, canal_tipo: str, tem_destaque: bool = False):
    """Registra um post do usuário - VERSÃO ATUALIZADA"""
    posts_db = load_posts_db()
    user_posts = posts_db.get(str(user_id), {})
    agora = int(time.time())
    
    # Registrar último post por tipo
    if canal_tipo == "vendedor":
        user_posts["ultimo_post_vendedor"] = agora
        user_posts["posts_rede"] = user_posts.get("posts_rede", 0) + 1
    elif canal_tipo == "comprador":
        user_posts["ultimo_post_comprador"] = agora
        
        # Para comprador verde, atualizar contador do período
        db = load_planos_db()
        for plano in db:
            if (plano["user_id"] == user_id and 
                plano["tipo"] == "comprador" and 
                plano.get("pago", False) and
                plano.get("data_fim", 0) > agora):
                
                plano_info = next((p for p in PLANOS if p["id_plano"] == plano["id_plano"]), None)
                if plano_info and plano_info["id_plano"] == 8:  # Comprador Verde
                    posts_no_periodo = user_posts.get("posts_periodo_comprador", {"inicio": 0, "count": 0})
                    posts_no_periodo["count"] += 1
                    user_posts["posts_periodo_comprador"] = posts_no_periodo
                break
    
    # Registrar uso de destaque
    if tem_destaque:
        user_posts["destaques_usados"] = user_posts.get("destaques_usados", 0) + 1
    
    posts_db[str(user_id)] = user_posts
    save_posts_db(posts_db)

async def mover_para_destaques(message: discord.Message):
    """Move uma mensagem com tag de destaque para o canal de destaques"""
    try:
        guild = message.guild
        canal_destaques = discord.utils.get(guild.channels, name=CHANNEL_CONFIG["destaques"])
        
        if not canal_destaques:
            print(f"Canal {CHANNEL_CONFIG['destaques']} não encontrado")
            return
        
        embed = discord.Embed(
            title="💯 Post em Destaque",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.set_footer(text=f"Original em #{message.channel.name}")
        embed.timestamp = message.created_at
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        
        await canal_destaques.send(embed=embed)
        print(f"Post de {message.author.display_name} movido para destaques")
        
    except Exception as e:
        print(f"Erro ao mover para destaques: {e}")

# ================== MERCADO PAGO ==================
def criar_assinatura_recorrente(plano: dict, user_id: int, username: str):
    """Cria assinatura recorrente mensal (só cartão)"""
    try:
        referencia = f"sub_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        
        subscription_data = {
            "reason": f"Assinatura {plano['descricao']}",
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": plano["preco"],
                "currency_id": "BRL"
            },
            "payer_email": f"user{user_id}@discord.bot",
            "card_token_id": "CARD_TOKEN",  # Obtido do frontend
            "status": "authorized",
            "external_reference": referencia
        }
        
        response = sdk.subscription().create(subscription_data)
        
        if response["status"] == 201:
            return response["response"]
        else:
            print(f"Erro ao criar assinatura: {response}")
            return None
            
    except Exception as e:
        print(f"Erro na assinatura recorrente: {e}")
        return None

def cancelar_assinatura_mp(subscription_id: str):
    """Cancela assinatura no Mercado Pago"""
    try:
        response = sdk.subscription().update(subscription_id, {"status": "cancelled"})
        return response["status"] == 200
    except Exception as e:
        print(f"Erro ao cancelar assinatura MP: {e}")
        return False
def gerar_chave_pix_aleatoria():
    import uuid
    return str(uuid.uuid4())

def criar_preferencia_pagamento(plano: dict, user_id: int, username: str):
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        referencia = f"plano_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        preference_data = {
            "items": [
                {
                    "title": f"Plano {plano['descricao']}",
                    "quantity": 1,
                    "unit_price": plano["preco"],
                    "currency_id": "BRL",
                    "description": f"Plano {plano['tipo']} - Discord Bot"
                }
            ],
            "payer": {
                "name": nome_usuario,
                "surname": "Discord User"
            },
            "payment_methods": {
                "excluded_payment_methods": [],
                "excluded_payment_types": [],
                "installments": 12
            },
            "back_urls": {
                "success": "https://www.cleitodiscord.com/success",
                "failure": "https://www.cleitodiscord.com/failure", 
                "pending": "https://www.cleitodiscord.com/pending"
            },
            "auto_return": "approved",
            "external_reference": referencia,
            "statement_descriptor": "DISCORD_BOT",
            "expires": True,
            "expiration_date_from": agora.isoformat(),
            "expiration_date_to": (agora + timedelta(hours=24)).isoformat()
        }
        
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response["status"] == 201:
            return preference_response["response"]
        else:
            print(f"Erro ao criar preferência: {preference_response}")
            return None
    except Exception as e:
        print(f"Erro ao criar preferência de pagamento: {e}")
        return None

def verificar_pagamento_por_referencia(external_reference):
    try:
        filters = {"external_reference": external_reference}
        search_response = sdk.payment().search(filters)
        
        if search_response["status"] == 200:
            results = search_response["response"]["results"]
            if results:
                return results[0]
        elif search_response["status"] == 429:
            print("Rate limit atingido - aguardando...")
            time.sleep(5)
            return None
        else:
            print(f"Erro na busca de pagamento: {search_response}")
        return None
    except Exception as e:
        print(f"Erro ao buscar pagamento: {e}")
        return None

def salvar_preferencia_pendente(preference_data, user_id, plano):
    try:
        payments_db = load_payments_db()
        
        payment_record = {
            "preference_id": preference_data["id"],
            "user_id": user_id,
            "plano": plano,
            "amount": plano["preco"],
            "status": "pending",
            "created_date": preference_data["date_created"],
            "checkout_link": preference_data["init_point"],
            "external_reference": preference_data.get("external_reference")
        }
        
        payments_db[str(preference_data["id"])] = payment_record
        save_payments_db(payments_db)
        return payment_record
    except Exception as e:
        print(f"Erro ao salvar preferência pendente: {e}")
        return None

def ativar_plano_apos_pagamento(user_id: int, plano: dict):
    try:
        db = load_planos_db()
        
        timestamp = int(time.time())
        duracao = 30 * 86400  # 30 dias
        
        plano_registro = {
            "user_id": user_id,
            "id_plano": plano["id_plano"],
            "descricao": plano["descricao"],
            "tipo": plano["tipo"],
            "pago": True,
            "data_inicio": timestamp,
            "data_fim": timestamp + duracao
        }
        
        db.append(plano_registro)
        save_planos_db(db)
        return plano_registro
    except Exception as e:
        print(f"Erro ao ativar plano: {e}")
        return None

# ================== ROLES DISCORD ==================
async def ensure_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        try:
            role = await guild.create_role(name=name, color=discord.Color.blue())
            print(f"Cargo '{name}' criado no servidor {guild.name}")
        except discord.Forbidden:
            print(f"Sem permissão para criar cargo: {name}")
            return None
        except Exception as e:
            print(f"Erro ao criar cargo {name}: {e}")
            return None
    return role

async def assign_role_to_member(member: discord.Member, tipo: str):
    try:
        role_name = tipo.capitalize()
        role = await ensure_role(member.guild, role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
            print(f"Cargo '{role_name}' atribuído a {member.display_name}")
            return True
        return True
    except discord.Forbidden:
        print(f"Sem permissão para adicionar cargo a {member.display_name}")
        return False
    except Exception as e:
        print(f"Erro ao atribuir cargo: {e}")
        return False

# ================== VIEWS ==================
class StatusPlanoView(View):
    def __init__(self, user_id, planos_ativos):
        super().__init__(timeout=None)  # Permanente
        self.user_id = user_id
        self.planos_ativos = planos_ativos
        self.expandido = False

    @discord.ui.button(label="👀 Ver Mais", style=discord.ButtonStyle.secondary)
    async def ver_mais(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Não é seu painel.", ephemeral=True)
            return
        
        self.expandido = True
        button.label = "📄 Ver Menos"
        button.emoji = "📄"
        
        embed = await self.gerar_embed_expandido()
        await interaction.response.edit_message(embed=embed, view=self)

    async def gerar_embed_expandido(self):
        """Gera embed com informações detalhadas"""
        db = load_planos_db()
        agora = int(time.time())
        
        embed = discord.Embed(
            title=f"📊 Histórico Completo - {interaction.user.display_name}",
            color=discord.Color.blue()
        )
        
        # Planos ativos
        if self.planos_ativos:
            texto_ativo = ""
            for plano in self.planos_ativos:
                dias_restantes = (plano.get("data_fim", 0) - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                data_inicio = datetime.fromtimestamp(plano.get("data_inicio", 0)).strftime("%d/%m/%Y")
                texto_ativo += f"🟢 **{plano['descricao']}** ({modalidade})\n"
                texto_ativo += f"   📅 Iniciado: {data_inicio}\n"
                texto_ativo += f"   ⏰ Restam: {dias_restantes} dias\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=texto_ativo, inline=False)
        
        # Histórico de cancelamentos
        cancelamentos = []
        for plano in db:
            if (plano["user_id"] == self.user_id and 
                plano.get("cancelado", False)):
                cancelamentos.append(plano)
        
        if cancelamentos:
            texto_cancelado = ""
            for plano in cancelamentos[-5:]:  # Últimos 5
                data_cancel = datetime.fromtimestamp(plano.get("data_cancelamento", 0)).strftime("%d/%m/%Y")
                taxa = plano.get("taxa_cancelamento", 0)
                modalidade = plano.get("modalidade", "mensal")
                texto_cancelado += f"🔴 **{plano['descricao']}** ({modalidade})\n"
                texto_cancelado += f"   📅 Cancelado: {data_cancel}\n"
                texto_cancelado += f"   💰 Taxa: {int(taxa*100)}%\n\n"
            
            embed.add_field(name="❌ Cancelamentos (últimos 5)", value=texto_cancelado, inline=False)
        
        return embed

    @discord.ui.button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
    async def cancelar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Não é seu painel.", ephemeral=True)
            return
        
        if not self.planos_ativos:
            await interaction.response.send_message("❌ Nenhum plano ativo para cancelar.", ephemeral=True)
            return
        
        view = CancelarPlanoView(self.planos_ativos)
        embed = discord.Embed(
            title="🗑️ Cancelar Plano",
            description="Escolha qual plano cancelar:",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🛒 Comprar Assinaturas", style=discord.ButtonStyle.success)
    async def comprar_assinaturas(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Redirecionar para comando !planos
        embed = discord.Embed(
            title="🛒 Comprar Assinaturas",
            description="Use o comando `!planos` para ver todas as opções disponíveis.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
class EscolherModalidadeView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Mensal", style=discord.ButtonStyle.green)
    async def modalidade_mensal(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="💰 Assinatura Mensal",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {self.plano['preco']:.2f}/mês",
            color=discord.Color.green()
        )
        embed.add_field(name="✅ Vantagens", value="• Cobrança automática todo mês\n• Cancelamento após 2 meses sem taxa", inline=False)
        
        view = EscolherPagamentoView(self.plano, "mensal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💎 Pagar 1 Vez (+50%)", style=discord.ButtonStyle.blurple)
    async def modalidade_unica(self, interaction: discord.Interaction, button: discord.ui.Button):
        preco_unico = self.plano['preco'] * 1.5
        embed = discord.Embed(
            title="💎 Pagamento Único",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {preco_unico:.2f} (única vez)",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="⚠️ Política de Cancelamento",
            value="• Antes de 2 meses: 100% de taxa\n• 2-6 meses: 35% de taxa\n• Após 6 meses: 15% de taxa",
            inline=False
        )
        
        view = EscolherPagamentoView(self.plano, "unico")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
class PagamentoViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=1800)
        self.plano = plano

    @discord.ui.button(label="💳 PIX/Cartão/Débito", style=discord.ButtonStyle.green, emoji="💰")
    async def abrir_checkout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento. Tente novamente em alguns minutos.", ephemeral=True)
                return
            
            payment_record = salvar_preferencia_pendente(preferencia, interaction.user.id, self.plano)
            
            if not payment_record:
                await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="💳 Pagamento Criado!",
                description=f"**Plano:** {self.plano['descricao']}\n**Valor:** R$ {self.plano['preco']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="💰 Formas de Pagamento Disponíveis:",
                value="• PIX (aprovação instantânea)\n• Cartão de Crédito (até 12x)\n• Cartão de Débito",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            embed.add_field(name="⏰ Validade", value="30 minutos", inline=True)
            embed.add_field(name="🔍 Status", value="Aguardando pagamento", inline=True)
            
            embed.add_field(
                name="📋 Como pagar:",
                value="1. Clique no link acima\n2. Escolha: PIX, Cartão ou Débito\n3. Complete o pagamento\n4. Volte aqui e clique 'Verificar Pagamento'",
                inline=False
            )
            
            embed.set_footer(text=f"ID: {preferencia['id']} - Plano ativa após confirmação")
            
            verificar_view = VerificarPagamentoViewCompleta(preferencia["external_reference"], interaction.user.id, self.plano)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no checkout: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

class VerificarPagamentoViewCompleta(View):
    def __init__(self, external_reference, user_id, plano):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda. Se você acabou de pagar, aguarde alguns minutos.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado com sucesso!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor Pago", value=f"R$ {self.plano['preco']:.2f}", inline=True)
                embed.add_field(name="🎯 Tipo", value=self.plano['tipo'].capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
                payments_db = load_payments_db()
                for payment_id, payment_data in payments_db.items():
                    if payment_data.get("external_reference") == self.external_reference:
                        payment_data["status"] = "approved"
                        save_payments_db(payments_db)
                        break
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando. Aguarde alguns minutos e tente novamente.", ephemeral=True)
                
            elif pagamento["status"] == "rejected":
                embed = discord.Embed(
                    title="❌ Pagamento Rejeitado",
                    description="Seu pagamento foi rejeitado. Tente novamente ou use outro método.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}. Continue aguardando ou tente novamente.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)

class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        try:
            db = load_planos_db()
            agora = int(time.time())
            
            for plano_ativo in db:
                if (plano_ativo["user_id"] == user_id and 
                    plano_ativo["tipo"] == self.plano["tipo"] and 
                    plano_ativo.get("pago", False) and
                    plano_ativo.get("data_fim", 0) > agora):
                    await interaction.response.send_message(
                        f"❌ Você já possui um plano ativo do tipo **{self.plano['tipo']}**!", 
                        ephemeral=True
                    )
                    return
            
            embed = discord.Embed(
                title="💳 Finalizar Compra",
                description=f"**Plano:** {self.plano['descricao']}\n**💰 Valor:** R$ {self.plano['preco']:.2f}",
                color=discord.Color.blue()
            )
            
            info = f"**Tipo:** {self.plano['tipo'].capitalize()}\n"
            
            if self.plano["id_plano"] == 2:  # Vendedor Verde
                info += "📅 **Postagem:** Alternada (hoje não, amanhã sim)\n"
            elif self.plano["id_plano"] == 8:  # Comprador Verde
                info += "📅 **Postagem:** 2 posts a cada 2 dias\n"
            elif "dias_post" in self.plano:
                if self.plano["dias_post"] == 1:
                    info += "📅 **Postagem:** Diária\n"
                else:
                    info += f"📅 **Postagem:** A cada {self.plano['dias_post']} dias\n"
            
            if "tags" in self.plano:
                if self.plano["tags"] == "ilimitado":
                    info += "🏷️ **Destaques:** Ilimitados\n"
                elif "posts_necessarios" in self.plano:
                    info += f"🏷️ **Destaques:** {self.plano['tags']} a cada {self.plano['posts_necessarios']} posts\n"
                else:
                    info += f"🏷️ **Tags disponíveis:** {self.plano['tags']}\n"
            
            embed.add_field(name="ℹ️ Detalhes", value=info, inline=False)
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.add_field(name="💳 Formas de Pagamento", value="PIX, Cartão Crédito/Débito", inline=True)
            
            embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
            
            pagamento_view = PagamentoViewCompleta(self.plano)
            await interaction.response.send_message(embed=embed, view=pagamento_view, ephemeral=True)
        
        except Exception as e:
            print(f"Erro na compra: {e}")
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)

class SelecionarPlanoView(View):
    def __init__(self):
        super().__init__(timeout=300)
        
        options = []
        for plano in PLANOS:
            emoji = "🔴" if "Vermelho" in plano["descricao"] else "🟢" if "Verde" in plano["descricao"] else "🔵"
            
            # Descrição personalizada para cada plano
            desc = f"Tipo: {plano['tipo'].capitalize()}"
            if plano["id_plano"] == 2:  # Vendedor Verde
                desc += " - Alternado"
            elif plano["id_plano"] == 4:  # Destacar Vermelho  
                desc += " - Ilimitado"
            elif plano["id_plano"] == 8:  # Comprador Verde
                desc += " - 2 posts/2 dias"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} - R$ {plano['preco']:.2f}",
                value=str(plano["id_plano"]),
                emoji=emoji,
                description=desc
            ))
        
        self.select = discord.ui.Select(
            placeholder="Escolha um plano...",
            options=options[:25],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        plano = next((p for p in PLANOS if p["id_plano"] == selected_id), None)
        
        if plano:
            embed = discord.Embed(
                title=f"💰 {plano['descricao']}",
                description=f"**Preço:** R$ {plano['preco']:.2f}\n**Tipo:** {plano['tipo'].capitalize()}",
                color=discord.Color.green()
            )
            
            # Descrições específicas para cada plano
            if plano["id_plano"] == 2:  # Vendedor Verde
                embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
            elif plano["id_plano"] == 8:  # Comprador Verde
                embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
            elif "dias_post" in plano:
                if plano["dias_post"] == 1:
                    embed.add_field(name="📅 Postagem", value="Diária", inline=True)
                else:
                    embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
            
            if "tags" in plano:
                if plano["tags"] == "ilimitado":
                    embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
                elif "posts_necessarios" in plano:
                    embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
                else:
                    embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
            
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
            
            view = ComprarViewCompleta(plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ================== MONITORAMENTO DE MENSAGENS ==================
@bot.event
async def on_message(message):
    """Monitora mensagens para controlar posts e detectar tags de destaque"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)
    
    # Verificar se é um canal de postagem
    canal_nome = message.channel.name
    user_id = message.author.id
    
    # Post na rede (vendedores)
    if canal_nome == CHANNEL_CONFIG["rede"]:
        pode, resultado = pode_postar(user_id, "vendedor")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Verificar se tem tag de destaque
        tem_destaque = "💯Destaques" in message.content
        
        if tem_destaque:
            pode_destacar, resultado_destaque = pode_usar_destaque(user_id)
            if not pode_destacar:
                # Remover apenas a tag, não deletar a mensagem
                content_sem_tag = message.content.replace("💯Destaques", "").strip()
                await message.edit(content=content_sem_tag)
                await message.channel.send(
                    f"⚠️ {message.author.mention} {resultado_destaque} A tag foi removida do seu post.",
                    delete_after=15
                )
                tem_destaque = False
        
        # Registrar o post
        registrar_post(user_id, "vendedor", tem_destaque)
        
        # Mover para destaques se necessário
        if tem_destaque:
            await mover_para_destaques(message)
    
    # Post na recomendação (compradores)
    elif canal_nome == CHANNEL_CONFIG["recomendacao"]:
        pode, resultado = pode_postar(user_id, "comprador")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Compradores não podem usar tag de destaque
        if "💯Destaques" in message.content:
            content_sem_tag = message.content.replace("💯Destaques", "").strip()
            await message.edit(content=content_sem_tag)
            await message.channel.send(
                f"⚠️ {message.author.mention} A tag de destaque não é permitida neste canal.",
                delete_after=10
            )
        
        # Registrar o post
        registrar_post(user_id, "comprador", False)

# ================== VERIFICAÇÃO AUTOMÁTICA DE PAGAMENTOS ==================
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente a cada 5 minutos"""
    await bot.wait_until_ready()
    
    try:
        payments_db = load_payments_db()
        if not payments_db:
            return
        
        for payment_id, payment_data in payments_db.items():
            if payment_data["status"] == "pending":
                external_ref = payment_data.get("external_reference")
                if external_ref:
                    pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                    
                    if pagamento_atual and pagamento_atual["status"] == "approved":
                        user_id = payment_data["user_id"]
                        plano = payment_data["plano"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano)
                        
                        if plano_ativado:
                            user = bot.get_user(user_id)
                            if user:
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        
                                        try:
                                            embed = discord.Embed(
                                                title="✅ PAGAMENTO CONFIRMADO AUTOMATICAMENTE!",
                                                description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                color=discord.Color.green()
                                            )
                                            embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                            embed.add_field(name="💰 Valor", value=f"R$ {plano['preco']:.2f}", inline=True)
                                            
                                            await user.send(embed=embed)
                                        except discord.Forbidden:
                                            print(f"Não foi possível enviar DM para {user.display_name}")
                                        except Exception as e:
                                            print(f"Erro ao notificar usuário: {e}")
                                        break
                            
                            payments_db[payment_id]["status"] = "approved"
                            save_payments_db(payments_db)
                            
                            print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# ================== COMANDOS ==================
@bot.command(name="planos")
async def mostrar_planos(ctx):
    """Mostra todos os planos disponíveis"""
    try:
        embed = discord.Embed(
            title="💼 Planos Disponíveis",
            description="⚠️ **IMPORTANTE:** Planos só são ativados após confirmação do pagamento!\n\n🛒 Use o menu abaixo para escolher:",
            color=discord.Color.blue()
        )
        
        vendedor_info = ""
        comprador_info = ""
        destacar_info = ""
        
        for plano in PLANOS:
            preco = f"R$ {plano['preco']:.2f}"
            if plano["tipo"] == "vendedor":
                if plano["id_plano"] == 2:  # Verde
                    vendedor_info += f"• {plano['descricao']}: {preco} (alternado - hoje não, amanhã sim)\n"
                elif plano["dias_post"] == 1:
                    vendedor_info += f"• {plano['descricao']}: {preco} (diário)\n"
                else:
                    vendedor_info += f"• {plano['descricao']}: {preco} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "comprador":
                if plano["id_plano"] == 8:  # Verde
                    comprador_info += f"• {plano['descricao']}: {preco} (2 posts a cada 2 dias)\n"
                elif plano["dias_post"] == 1:
                    comprador_info += f"• {plano['descricao']}: {preco} (diário)\n"
                else:
                    comprador_info += f"• {plano['descricao']}: {preco} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "destacar":
                if plano["tags"] == "ilimitado":
                    destacar_info += f"• {plano['descricao']}: {preco} (destaques ilimitados)\n"
                elif "posts_necessarios" in plano:
                    destacar_info += f"• {plano['descricao']}: {preco} ({plano['tags']} destaque(s) a cada {plano['posts_necessarios']} posts)\n"
                else:
                    destacar_info += f"• {plano['descricao']}: {preco} ({plano['tags']} destaque(s))\n"
        
        if vendedor_info:
            embed.add_field(name="🛍️ Planos Vendedor", value=vendedor_info, inline=True)
        if comprador_info:
            embed.add_field(name="🛒 Planos Comprador", value=comprador_info, inline=True)
        if destacar_info:
            embed.add_field(name="⭐ Planos Destacar", value=destacar_info, inline=True)
        
        embed.add_field(
            name="📋 Informações dos Canais",
            value=f"• **Vendedores:** Postem na {CHANNEL_CONFIG['rede']}\n• **Compradores:** Postem na {CHANNEL_CONFIG['recomendacao']}\n• **Destaques:** Posts com 💯Destaques vão para {CHANNEL_CONFIG['destaques']}",
            inline=False
        )
        
        embed.add_field(
            name="💳 Formas de Pagamento",
            value="• PIX (aprovação instantânea)\n• Cartão de Crédito (até 12x)\n• Cartão de Débito",
            inline=False
        )
        
        view = SelecionarPlanoView()
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar planos: {e}")
        await ctx.send("❌ Erro ao carregar planos. Tente novamente.")

@bot.command(name="plano")
async def plano_individual(ctx, id_plano: int = None):
    """Comprar plano específico por ID: !plano 1, !plano 2, etc"""
    if id_plano is None:
        embed = discord.Embed(
            title="❓ Como usar",
            description="Use: `!plano <número>`\n\n**Exemplos:**\n• `!plano 1` - Vendedor Vermelho\n• `!plano 2` - Vendedor Verde\n• `!plano 3` - Vendedor Azul",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="📋 Lista de IDs",
            value="\n".join([f"`{p['id_plano']}` - {p['descricao']}" for p in PLANOS[:5]]) + f"\n\n*Use `!planos` para ver todos*",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    plano = next((p for p in PLANOS if p["id_plano"] == id_plano), None)
    if not plano:
        await ctx.send(f"❌ Plano {id_plano} não encontrado. Use `!planos` para ver todos os planos disponíveis.")
        return
    
    try:
        embed = discord.Embed(
            title=f"Plano {id_plano}: {plano['descricao']}",
            description=f"**Preço:** R$ {plano['preco']:.2f}\n**Tipo:** {plano['tipo'].capitalize()}",
            color=discord.Color.blue()
        )
        
        # Descrições específicas para cada plano
        if plano["id_plano"] == 2:  # Vendedor Verde
            embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
        elif plano["id_plano"] == 8:  # Comprador Verde
            embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
        elif "dias_post" in plano:
            if plano["dias_post"] == 1:
                embed.add_field(name="📅 Postagem", value="Diária", inline=True)
            else:
                embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
        
        if "tags" in plano:
            if plano["tags"] == "ilimitado":
                embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
            elif "posts_necessarios" in plano:
                embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
            else:
                embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
        
        embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
        embed.set_footer(text="⚠️ Plano só é ativado após confirmação do pagamento!")
        
        view = ComprarViewCompleta(plano)
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar plano individual: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.")

@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        posts_db = load_posts_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_encontrados = False
        planos_ativos = []
        planos_expirados = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                planos_encontrados = True
                fim = plano.get("data_fim", agora)
                
                if agora > fim:
                    planos_expirados.append(plano)
                else:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                ativo_text += f"• **{plano['descricao']}**\n  📅 {dias_restantes} dias restantes\n  🎯 Tipo: {plano['tipo'].capitalize()}\n\n"
            
            embed.add_field(
                name="✅ Planos Ativos",
                value=ativo_text,
                inline=False
            )
        
        # Mostrar estatísticas de posts para planos de destaque
        user_posts = posts_db.get(str(user_id), {})
        if any(p["tipo"] == "destacar" for p in planos_ativos):
            posts_rede = user_posts.get("posts_rede", 0)
            destaques_usados = user_posts.get("destaques_usados", 0)
            
            embed.add_field(
                name="📊 Estatísticas de Destaque",
                value=f"• Posts na rede: {posts_rede}\n• Destaques usados: {destaques_usados}",
                inline=True
            )
        
        # Mostrar estatísticas de posts para comprador verde
        if any(p["id_plano"] == 8 for p in planos_ativos):  # Comprador Verde
            posts_periodo = user_posts.get("posts_periodo_comprador", {"count": 0})
            embed.add_field(
                name="📊 Posts no Período Atual",
                value=f"• Posts usados: {posts_periodo.get('count', 0)}/2",
                inline=True
            )
        
        if planos_expirados:
            expirado_text = ""
            for plano in planos_expirados[-3:]:
                expirado_text += f"• {plano['descricao']}\n"
            
            embed.add_field(
                name="❌ Planos Expirados (últimos 3)",
                value=expirado_text,
                inline=False
            )
        
        if not planos_encontrados:
            embed.description = "Nenhum plano ativo encontrado.\n\n🛍️ Use `!planos` para ver as opções disponíveis!"
            embed.color = discord.Color.orange()
        
        embed.add_field(
            name="📋 Comandos Úteis",
            value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!ajuda` - Todos os comandos",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status. Tente novamente.")

@bot.command(name="ajuda", aliases=["help"])
async def ajuda(ctx):
    """Comandos disponíveis"""
    embed = discord.Embed(
        title="🤖 Central de Ajuda - Discord Bot",
        description="Sistema completo de planos com pagamentos reais via Mercado Pago",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="🛍️ Comandos de Compra",
        value="• `!planos` - Ver todos os planos disponíveis\n• `!plano <id>` - Comprar plano específico (ex: `!plano 1`)\n• `!status` - Ver seus planos ativos",
        inline=False
    )
    
    embed.add_field(
        name="🌟 Sistema Privado",
        value="• `!assinatura` - Acessar seu espaço privado de assinatura\n• `!assinar` - Alias para o comando acima\n• `!privado` - Outro alias para privacidade",
        inline=False
    )
    
    embed.add_field(
        name="📋 Tipos de Planos ATUALIZADOS",
        value=f"• **Vendedor** - Para postar na {CHANNEL_CONFIG['rede']}\n  - Verde: Alternado (hoje não, amanhã sim)\n  - Vermelho: Diário\n  - Azul: A cada 2 dias\n• **Comprador** - Para postar na {CHANNEL_CONFIG['recomendacao']}\n  - Verde: 2 posts a cada 2 dias\n  - Vermelho: Diário\n  - Azul: A cada 2 dias\n• **Destacar** - Para usar a tag 💯Destaques\n  - Vermelho: Ilimitado\n  - Verde/Azul: Baseado em posts",
        inline=False
    )
    
    embed.add_field(
        name="🏷️ Sistema de Destaques",
        value=f"• Tag **💯Destaques** só funciona na {CHANNEL_CONFIG['rede']}\n• Posts destacados aparecem automaticamente no {CHANNEL_CONFIG['destaques']}\n• **Vermelho:** Ilimitado\n• **Verde:** 2 destaques a cada 10 posts\n• **Azul:** 1 destaque a cada 10 posts",
        inline=False
    )
    
    embed.add_field(
        name="🔒 Privacidade Garantida",
        value=f"• Use `!assinatura` para acessar seu espaço privado\n• Localizado na categoria **{CHANNEL_CONFIG['categoria_assinaturas']}**\n• Apenas você pode ver suas conversas\n• Todos os comandos funcionam no espaço privado",
        inline=False
    )
    
    embed.add_field(
        name="💳 Formas de Pagamento",
        value="• **PIX** - Aprovação instantânea\n• **Cartão de Crédito** - Até 12x sem juros\n• **Cartão de Débito** - Aprovação rápida",
        inline=True
    )
    
    embed.add_field(
        name="⚡ Processo de Compra",
        value="1. Use `!assinatura` para privacidade\n2. Escolha o plano com `!planos`\n3. Efetue o pagamento\n4. Aguarde confirmação automática\n5. Plano ativado!",
        inline=True
    )
    
    embed.add_field(
        name="⏰ Informações Importantes",
        value="• **Duração:** Todos os planos duram 30 dias\n• **Ativação:** Automática após pagamento confirmado\n• **Verificação:** Sistema verifica pagamentos a cada 5 minutos\n• **Cooldown:** Respeitado automaticamente conforme plano",
        inline=False
    )
    
    embed.set_footer(text="💡 Dica: Use !assinatura para começar com privacidade!")
    
    await ctx.send(embed=embed)

@bot.command(name="limpar", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def limpar_planos_expirados(ctx, confirmar: str = None):
    """Remove planos expirados do banco de dados (apenas administradores)"""
    if confirmar != "SIM":
        embed = discord.Embed(
            title="⚠️ Confirmação Necessária",
            description="Este comando irá remover TODOS os planos expirados do banco de dados.\n\nPara confirmar, use: `!limpar SIM`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        planos_ativos = []
        removidos = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos.append(plano)
            else:
                removidos += 1
        
        save_planos_db(planos_ativos)
        
        embed = discord.Embed(
            title="🧹 Limpeza Concluída",
            description=f"**{removidos}** planos expirados foram removidos.\n**{len(planos_ativos)}** planos ativos mantidos.",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro na limpeza: {e}")
        await ctx.send("❌ Erro ao limpar banco de dados.")

@bot.command(name="assinatura", aliases=["assinar", "privado"])
async def acessar_assinatura_privada(ctx):
    """Cria ou acessa seu espaço privado de assinatura"""
    try:
        # Configurar fórum se necessário
        forum_configurado = await garantir_forum_configurado(ctx.guild)
        if not forum_configurado:
            await ctx.send("❌ Erro ao configurar sistema de fórum. Contate um administrador.", delete_after=10)
            return
        
        # Obter ou criar thread privada
        thread_privada = await obter_ou_criar_thread_privada(ctx.author, ctx.guild)
        
        if not thread_privada:
            await ctx.send("❌ Erro ao criar/acessar seu espaço privado. Tente novamente.", delete_after=10)
            return
        
        # Resposta pública temporária
        embed = discord.Embed(
            title="✅ Espaço Privado Criado!",
            description=f"Seu espaço privado de assinatura foi criado!\n\n🔗 **Acesse:** {thread_privada.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🔒 Privacidade",
            value="• Apenas você pode ver e interagir\n• Comandos do bot funcionam normalmente\n• Totalmente confidencial",
            inline=False
        )
        embed.set_footer(text="Esta mensagem será deletada em 15 segundos")
        
        await ctx.send(embed=embed, delete_after=15)
        
        # Deletar comando do usuário por privacidade
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        
        # Mensagem de boas-vindas na thread privada
        if thread_privada.message_count <= 1:  # Se é nova thread
            welcome_embed = discord.Embed(
                title="🎉 Bem-vindo ao seu espaço privado!",
                description="Este é seu ambiente privado para gerenciar assinaturas e planos.",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(
                name="🛍️ Comandos Disponíveis:",
                value="• `!planos` - Ver planos disponíveis\n• `!status` - Seus planos ativos\n• `!plano <id>` - Comprar plano específico",
                inline=False
            )
            welcome_embed.add_field(
                name="🔒 Privacidade Garantida:",
                value="• Ninguém mais pode ver este chat\n• Seus dados estão seguros\n• Pagamentos processados com segurança",
                inline=False
            )
            
            await thread_privada.send(embed=welcome_embed)
        
    except Exception as e:
        print(f"Erro no comando assinatura: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.command(name="stats")
@commands.has_permissions(administrator=True)
async def estatisticas_bot(ctx):
    """Mostra estatísticas do bot (apenas administradores)"""
    try:
        db = load_planos_db()
        payments_db = load_payments_db()
        posts_db = load_posts_db()
        agora = int(time.time())
        
        planos_ativos = 0
        planos_expirados = 0
        total_arrecadado = 0
        pagamentos_pendentes = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos += 1
            else:
                planos_expirados += 1
        
        for payment_data in payments_db.values():
            if payment_data["status"] == "approved":
                total_arrecadado += payment_data.get("amount", 0)
            elif payment_data["status"] == "pending":
                pagamentos_pendentes += 1
        
        tipos = {"vendedor": 0, "comprador": 0, "destacar": 0}
        for plano in db:
            if plano.get("data_fim", 0) > agora:
                tipo = plano.get("tipo", "")
                if tipo in tipos:
                    tipos[tipo] += 1
        
        total_posts_rede = sum(user_data.get("posts_rede", 0) for user_data in posts_db.values())
        total_destaques = sum(user_data.get("destaques_usados", 0) for user_data in posts_db.values())
        
        embed = discord.Embed(
            title="📊 Estatísticas do Bot",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📈 Planos",
            value=f"**Ativos:** {planos_ativos}\n**Expirados:** {planos_expirados}\n**Total:** {planos_ativos + planos_expirados}",
            inline=True
        )
        
        embed.add_field(
            name="💰 Financeiro",
            value=f"**Arrecadado:** R$ {total_arrecadado:.2f}\n**Pendentes:** {pagamentos_pendentes}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Por Tipo (Ativos)",
            value=f"**Vendedor:** {tipos['vendedor']}\n**Comprador:** {tipos['comprador']}\n**Destacar:** {tipos['destacar']}",
            inline=True
        )
        
        embed.add_field(
            name="📊 Atividade",
            value=f"**Posts na rede:** {total_posts_rede}\n**Destaques usados:** {total_destaques}",
            inline=True
        )
        
        embed.add_field(
            name="🤖 Bot Info",
            value=f"**Servidores:** {len(bot.guilds)}\n**Usuários:** {len(set(bot.get_all_members()))}",
            inline=True
        )
        
        embed.set_footer(text=f"Última verificação: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro nas estatísticas: {e}")
        await ctx.send("❌ Erro ao gerar estatísticas.")

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} está online!")
    print(f"📊 Conectado a {len(bot.guilds)} servidor(s)")
    print(f"👥 Alcançando {len(set(bot.get_all_members()))} usuários únicos")
    print(f"💳 Mercado Pago integrado - Sistema de cobrança REAL ativo")
    print(f"⚠️  Planos só são ativados após confirmação de pagamento!")
    print(f"🏷️  Sistema de destaques integrado com canais: {CHANNEL_CONFIG}")
    print("🔄 PLANOS ATUALIZADOS:")
    print("   • Vendedor Verde: Alternado (hoje não, amanhã sim)")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Ilimitado")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
        print("🔄 Verificação automática de pagamentos iniciada (a cada 5 minutos)")

@bot.event
async def on_command_error(ctx, error):
    """Tratamento de erros dos comandos"""
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❓ Comando não encontrado",
            description=f"O comando `{ctx.message.content}` não existe.\n\nUse `!ajuda` para ver todos os comandos disponíveis.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumento inválido. Verifique o comando e tente novamente.", delete_after=5)
    
    else:
        print(f"Erro no comando {ctx.command}: {error}")
        await ctx.send("❌ Erro interno. Tente novamente mais tarde.", delete_after=5)

@bot.event
async def on_guild_join(guild):
    """Quando o bot entra em um servidor novo"""
    print(f"➕ Bot adicionado ao servidor: {guild.name} (ID: {guild.id})")
    
    # Configurar fórum automaticamente
    await garantir_forum_configurado(guild)
    
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="🎉 Obrigado por me adicionar!",
                description="Sou um bot de **venda de planos** com pagamentos reais via Mercado Pago!",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🚀 Como começar",
                value="• `!ajuda` - Ver todos os comandos\n• `!assinatura` - Acessar espaço privado\n• `!planos` - Ver planos disponíveis\n• `!status` - Verificar seus planos",
                inline=False
            )
            
            embed.add_field(
                name="🔒 Sistema Privado",
                value="• Use `!assinatura` para ter privacidade total\n• Cada usuário tem seu espaço individual\n• Ninguém pode ver suas conversas ou compras",
                inline=False
            )
            
            embed.add_field(
                name="💳 Sobre os Pagamentos",
                value="• Pagamentos **100% reais** via Mercado Pago\n• PIX, Cartão de Crédito e Débito\n• Ativação automática após confirmação",
                inline=False
            )
            
            embed.add_field(
                name="🏷️ Configuração dos Canais",
                value=f"• Crie o canal **{CHANNEL_CONFIG['rede']}** para vendedores\n• Crie o canal **{CHANNEL_CONFIG['recomendacao']}** para compradores\n• Crie o canal **{CHANNEL_CONFIG['destaques']}** para posts destacados\n• Categoria **{CHANNEL_CONFIG['categoria_assinaturas']}** criada automaticamente",
                inline=False
            )
            
            embed.add_field(
                name="🆕 PLANOS ATUALIZADOS",
                value="• **Vendedor Verde:** Alternado (hoje não, amanhã sim)\n• **Comprador Verde:** 2 posts a cada 2 dias\n• **Destacar Vermelho:** Destaques ilimitados",
                inline=False
            )
            
            embed.set_footer(text="Digite !assinatura para começar com total privacidade!")
            
            try:
                await channel.send(embed=embed)
                break
            except discord.Forbidden:
                continue

@bot.event
async def on_member_join(member):
    """Quando um usuário entra no servidor"""
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        for plano in db:
            if (plano["user_id"] == member.id and 
                plano.get("pago", False) and 
                plano.get("data_fim", 0) > agora):
                
                await assign_role_to_member(member, plano["tipo"])
                print(f"Cargo {plano['tipo']} reatribuído para {member.display_name}")
                
    except Exception as e:
        print(f"Erro ao reatribuir cargos para {member.display_name}: {e}")

# ================== INICIALIZAÇÃO ==================
if __name__ == "__main__":
    print("🚀 Iniciando Discord Bot...")
    print("💳 Sistema de cobrança REAL ativo via Mercado Pago")
    print("⚠️  IMPORTANTE: Planos só são ativados após confirmação de pagamento!")
    print("🔄 Verificação automática de pagamentos a cada 5 minutos")
    print(f"🏷️ Canais configurados: {CHANNEL_CONFIG}")
    print("🆕 ATUALIZAÇÕES DOS PLANOS:")
    print("   • Vendedor Verde: Sistema alternado")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Destaques ilimitados")
    print("=" * 60)
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if not ML_TOKEN:
        print("❌ ML_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if ML_TOKEN.startswith("APP_USR"):
        print("🚨 ATENÇÃO: Usando tokens de PRODUÇÃO - Cobranças serão REAIS!")
    elif ML_TOKEN.startswith("TEST"):
        print("🧪 Usando tokens de TESTE - Ambiente de desenvolvimento")
    else:
        print("⚠️  Token do Mercado Pago não identificado")
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ TOKEN do Discord inválido! Verifique o arquivo .env")
    except discord.HTTPException as e:
        print(f"❌ Erro HTTP: {e}")
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado pelo usuário")
    except Exception as e:
        print(f"❌ Erro inesperado ao iniciar bot: {e}")
    finally:
        print("🔴 Bot desconectado")
        # ================== MONITORAMENTO DE MENSAGENS ==================
@bot.event
async def on_message(message):
    """Monitora mensagens para controlar posts e detectar tags de destaque"""
    if message.author.bot:
        return
    
    await bot.process_commands(message)
    
    # Verificar se é um canal de postagem
    canal_nome = message.channel.name
    user_id = message.author.id
    
    # Post na rede (vendedores)
    if canal_nome == CHANNEL_CONFIG["rede"]:
        pode, resultado = pode_postar(user_id, "vendedor")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Verificar se tem tag de destaque
        tem_destaque = "💯Destaques" in message.content
        
        if tem_destaque:
            pode_destacar, resultado_destaque = pode_usar_destaque(user_id)
            if not pode_destacar:
                content_sem_tag = message.content.replace("💯Destaques", "").strip()
                await message.edit(content=content_sem_tag)
                await message.channel.send(
                    f"⚠️ {message.author.mention} {resultado_destaque} A tag foi removida do seu post.",
                    delete_after=15
                )
                tem_destaque = False
        
        # Registrar o post
        registrar_post(user_id, "vendedor", tem_destaque)
        
        # Mover para destaques se necessário
        if tem_destaque:
            await mover_para_destaques(message)
    
    # Post na recomendação (compradores)
    elif canal_nome == CHANNEL_CONFIG["recomendacao"]:
        pode, resultado = pode_postar(user_id, "comprador")
        if not pode:
            await message.delete()
            await message.channel.send(
                f"❌ {message.author.mention} {resultado}",
                delete_after=10
            )
            return
        
        # Compradores não podem usar tag de destaque
        if "💯Destaques" in message.content:
            content_sem_tag = message.content.replace("💯Destaques", "").strip()
            await message.edit(content=content_sem_tag)
            await message.channel.send(
                f"⚠️ {message.author.mention} A tag de destaque não é permitida neste canal.",
                delete_after=10
            )
        
        # Registrar o post
        registrar_post(user_id, "comprador", False)

# ================== VERIFICAÇÃO AUTOMÁTICA DE PAGAMENTOS ==================
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente a cada 5 minutos"""
    await bot.wait_until_ready()
    
    try:
        # Verificar pagamentos de cartão
        payments_db = load_payments_db()
        if payments_db:
            for payment_id, payment_data in payments_db.items():
                if payment_data["status"] == "pending":
                    external_ref = payment_data.get("external_reference")
                    if external_ref:
                        pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                        
                        if pagamento_atual and pagamento_atual["status"] == "approved":
                            user_id = payment_data["user_id"]
                            plano = payment_data["plano"]
                            modalidade = external_ref.split("_")[-1] if "_" in external_ref else "mensal"
                            
                            plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                            
                            if plano_ativado:
                                user = bot.get_user(user_id)
                                if user:
                                    for guild in bot.guilds:
                                        member = guild.get_member(user_id)
                                        if member:
                                            await assign_role_to_member(member, plano["tipo"])
                                            
                                            try:
                                                embed = discord.Embed(
                                                    title="✅ PAGAMENTO CONFIRMADO AUTOMATICAMENTE!",
                                                    description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                    color=discord.Color.green()
                                                )
                                                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                                embed.add_field(name="🎯 Modalidade", value=modalidade.capitalize(), inline=True)
                                                
                                                await user.send(embed=embed)
                                            except discord.Forbidden:
                                                print(f"Não foi possível enviar DM para {user.display_name}")
                                            except Exception as e:
                                                print(f"Erro ao notificar usuário: {e}")
                                            break
                                
                                payments_db[payment_id]["status"] = "approved"
                                save_payments_db(payments_db)
                                
                                print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
        
        # Verificar pagamentos PIX
        pix_db = load_pix_db()
        if pix_db:
            for payment_id, pix_data in pix_db.items():
                if pix_data["status"] == "pending":
                    pagamento_pix = verificar_pagamento_pix(payment_id)
                    
                    if pagamento_pix and pagamento_pix["status"] == "approved":
                        user_id = pix_data["user_id"]
                        plano = pix_data["plano"]
                        modalidade = pix_data["modalidade"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                        
                        if plano_ativado:
                            user = bot.get_user(user_id)
                            if user:
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        
                                        try:
                                            embed = discord.Embed(
                                                title="✅ PIX CONFIRMADO AUTOMATICAMENTE!",
                                                description=f"Seu plano **{plano['descricao']}** foi ativado!",
                                                color=discord.Color.green()
                                            )
                                            embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                                            embed.add_field(name="🎯 Modalidade", value=modalidade.capitalize(), inline=True)
                                            embed.add_field(name="💰 Valor", value=f"R$ {pix_data['amount']:.2f}", inline=True)
                                            
                                            await user.send(embed=embed)
                                        except discord.Forbidden:
                                            print(f"Não foi possível enviar DM para {user.display_name}")
                                        except Exception as e:
                                            print(f"Erro ao notificar usuário: {e}")
                                        break
                            
                            pix_db[payment_id]["status"] = "approved"
                            save_pix_db(pix_db)
                            
                            print(f"✅ Plano PIX {plano['descricao']} ativado automaticamente para usuário {user_id}")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# ================== COMANDOS ==================
@bot.command(name="planos")
async def mostrar_planos(ctx):
    """Mostra todos os planos disponíveis"""
    try:
        embed = discord.Embed(
            title="💼 Planos Disponíveis",
            description="🛍️ Escolha entre **Mensal** ou **Pagamento Único (+50%)**\n\n🛒 Use o menu abaixo para escolher:",
            color=discord.Color.blue()
        )
        
        vendedor_info = ""
        comprador_info = ""
        destacar_info = ""
        
        for plano in PLANOS:
            preco = f"R$ {plano['preco']:.2f}"
            preco_unico = f"R$ {plano['preco'] * 1.5:.2f}"
            
            if plano["tipo"] == "vendedor":
                if plano["id_plano"] == 2:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (alternado)\n"
                elif plano["dias_post"] == 1:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (diário)\n"
                else:
                    vendedor_info += f"• {plano['descricao']}: {preco} | {preco_unico} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "comprador":
                if plano["id_plano"] == 8:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (2 posts/2 dias)\n"
                elif plano["dias_post"] == 1:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (diário)\n"
                else:
                    comprador_info += f"• {plano['descricao']}: {preco} | {preco_unico} (a cada {plano['dias_post']} dias)\n"
            elif plano["tipo"] == "destacar":
                if plano["tags"] == "ilimitado":
                    destacar_info += f"• {plano['descricao']}: {preco} | {preco_unico} (ilimitado)\n"
                elif "posts_necessarios" in plano:
                    destacar_info += f"• {plano['descricao']}: {preco} | {preco_unico} ({plano['tags']} a cada {plano['posts_necessarios']} posts)\n"
        
        if vendedor_info:
            embed.add_field(name="🛍️ Vendedor (Mensal | Único)", value=vendedor_info, inline=True)
        if comprador_info:
            embed.add_field(name="🛒 Comprador (Mensal | Único)", value=comprador_info, inline=True)
        if destacar_info:
            embed.add_field(name="⭐ Destacar (Mensal | Único)", value=destacar_info, inline=True)
        
        embed.add_field(
            name="💎 Pagamento Único",
            value="• 50% a mais no valor\n• Válido por 1 mês\n• Taxa de cancelamento antes de 2 meses: 100%",
            inline=False
        )
        
        embed.add_field(
            name="💳 Formas de Pagamento",
            value="• **PIX** - Confirmação rápida\n• **Cartão** - Crédito/Débito (até 12x)",
            inline=False
        )
        
        view = SelecionarPlanoView()
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar planos: {e}")
        await ctx.send("❌ Erro ao carregar planos. Tente novamente.")

@bot.command(name="plano")
async def plano_individual(ctx, id_plano: int = None):
    """Comprar plano específico por ID"""
    if id_plano is None:
        embed = discord.Embed(
            title="❓ Como usar",
            description="Use: `!plano <número>`\n\n**Exemplos:**\n• `!plano 1` - Vendedor Vermelho\n• `!plano 2` - Vendedor Verde",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="📋 Lista de IDs",
            value="\n".join([f"`{p['id_plano']}` - {p['descricao']}" for p in PLANOS[:5]]) + "\n\n*Use `!planos` para ver todos*",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    plano = next((p for p in PLANOS if p["id_plano"] == id_plano), None)
    if not plano:
        await ctx.send(f"❌ Plano {id_plano} não encontrado. Use `!planos` para ver todos os planos disponíveis.")
        return
    
    try:
        embed = discord.Embed(
            title=f"Plano {id_plano}: {plano['descricao']}",
            description=f"**Mensal:** R$ {plano['preco']:.2f}\n**Único:** R$ {plano['preco'] * 1.5:.2f} (+50%)\n**Tipo:** {plano['tipo'].capitalize()}",
            color=discord.Color.blue()
        )
        
        if plano["id_plano"] == 2:
            embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
        elif plano["id_plano"] == 8:
            embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
        elif "dias_post" in plano:
            if plano["dias_post"] == 1:
                embed.add_field(name="📅 Postagem", value="Diária", inline=True)
            else:
                embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
        
        if "tags" in plano:
            if plano["tags"] == "ilimitado":
                embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
            elif "posts_necessarios" in plano:
                embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
        
        embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
        
        view = ComprarViewCompleta(plano)
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar plano individual: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.")

@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        posts_db = load_posts_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_encontrados = False
        planos_ativos = []
        planos_expirados = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                planos_encontrados = True
                fim = plano.get("data_fim", agora)
                
                if agora > fim:
                    planos_expirados.append(plano)
                else:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                ativo_text += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n  🎯 Tipo: {plano['tipo'].capitalize()}\n\n"
            
            embed.add_field(
                name="✅ Planos Ativos",
                value=ativo_text,
                inline=False
            )
            
            # Botão para cancelar planos
            view = View(timeout=300)
            cancelar_btn = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Você não pode usar este botão.", ephemeral=True)
                    return
                
                agora = int(time.time())
                planos_cancelaveis = [p for p in planos_ativos if p.get("data_fim", 0) > agora]
                
                if not planos_cancelaveis:
                    await interaction.response.send_message("❌ Nenhum plano ativo para cancelar.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_cancelaveis)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha o plano que deseja cancelar:",
                    color=discord.Color.orange()
                )
                embed_cancelar.add_field(
                    name="⚠️ Política de Cancelamento:",
                    value="• Antes de 2 meses: Taxa de 100%\n• Após 2 meses: Sem taxa\n• Pagamento único: Sempre taxa de 100%",
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            cancelar_btn.callback = cancelar_callback
            view.add_item(cancelar_btn)
            
            embed.set_footer(text="Use o botão abaixo para cancelar um plano")
        else:
            view = None
        
        # Estatísticas de posts
        user_posts = posts_db.get(str(user_id), {})
        if any(p["tipo"] == "destacar" for p in planos_ativos):
            posts_rede = user_posts.get("posts_rede", 0)
            destaques_usados = user_posts.get("destaques_usados", 0)
            
            embed.add_field(
                name="📊 Estatísticas de Destaque",
                value=f"• Posts na rede: {posts_rede}\n• Destaques usados: {destaques_usados}",
                inline=True
            )
        
        if any(p["id_plano"] == 8 for p in planos_ativos):
            posts_periodo = user_posts.get("posts_periodo_comprador", {"count": 0})
            embed.add_field(
                name="📊 Posts no Período Atual",
                value=f"• Posts usados: {posts_periodo.get('count', 0)}/2",
                inline=True
            )
        
        if planos_expirados:
            expirado_text = ""
            for plano in planos_expirados[-3:]:
                modalidade = plano.get("modalidade", "mensal")
                expirado_text += f"• {plano['descricao']} ({modalidade})\n"
            
            embed.add_field(
                name="❌ Planos Expirados (últimos 3)",
                value=expirado_text,
                inline=False
            )
        
        if not planos_encontrados:
            embed.description = "Nenhum plano ativo encontrado.\n\n🛍️ Use `!planos` para ver as opções disponíveis!"
            embed.color = discord.Color.orange()
        
        embed.add_field(
            name="📋 Comandos Úteis",
            value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!ajuda` - Todos os comandos",
            inline=False
        )
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status. Tente novamente.")

@bot.command(name="ajuda", aliases=["help"])
async def ajuda(ctx):
    """Comandos disponíveis"""
    embed = discord.Embed(
        title="🤖 Central de Ajuda - Sistema de Assinaturas",
        description="Sistema completo com PIX, Cartão e Cancelamentos",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="🛍️ Comandos de Compra",
        value="• `!planos` - Ver todos os planos\n• `!plano <id>` - Comprar plano específico\n• `!status` - Ver/cancelar seus planos",
        inline=False
    )
    
    embed.add_field(
        name="🌟 Sistema Privado",
        value="• `!assinatura` - Espaço privado de assinatura\n• `!assinar` - Alias para privacidade\n• `!privado` - Outro alias",
        inline=False
    )
    
    embed.add_field(
        name="💰 Modalidades de Pagamento",
        value="• **Mensal**: Preço normal, cancelamento flexível\n• **Único**: +50% do valor, válido 1 mês, taxa cancelamento\n• **PIX**: Confirmação rápida\n• **Cartão**: Crédito/Débito até 12x",
        inline=False
    )
    
    embed.add_field(
        name="🗑️ Sistema de Cancelamento",
        value="• Use `!status` e clique em 'Cancelar Plano'\n• Antes de 2 meses: Taxa de 100%\n• Após 2 meses: Sem taxa\n• Pagamento único: Sempre 100% de taxa",
        inline=False
    )
    
    embed.add_field(
        name="📋 Tipos de Planos",
        value="• **Vendedor Verde**: Alternado (hoje não, amanhã sim)\n• **Comprador Verde**: 2 posts a cada 2 dias\n• **Destacar Vermelho**: Destaques ilimitados",
        inline=False
    )
    
    embed.set_footer(text="💡 Use !assinatura para total privacidade!")
    
    await ctx.send(embed=embed)

@bot.command(name="limpar", aliases=["clear"])
@commands.has_permissions(manage_messages=True)
async def limpar_planos_expirados(ctx, confirmar: str = None):
    """Remove planos expirados do banco de dados"""
    if confirmar != "SIM":
        embed = discord.Embed(
            title="⚠️ Confirmação Necessária",
            description="Este comando irá remover TODOS os planos expirados.\n\nPara confirmar: `!limpar SIM`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        planos_ativos = []
        removidos = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos.append(plano)
            else:
                removidos += 1
        
        save_planos_db(planos_ativos)
        
        embed = discord.Embed(
            title="🧹 Limpeza Concluída",
            description=f"**{removidos}** planos expirados removidos.\n**{len(planos_ativos)}** planos ativos mantidos.",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro na limpeza: {e}")
        await ctx.send("❌ Erro ao limpar banco de dados.")

@bot.command(name="assinatura", aliases=["assinar", "privado"])
async def acessar_assinatura_privada(ctx):
    """Cria ou acessa seu espaço privado de assinatura"""
    try:
        forum_configurado = await garantir_forum_configurado(ctx.guild)
        if not forum_configurado:
            await ctx.send("❌ Erro ao configurar sistema de fórum. Contate um administrador.", delete_after=10)
            return
        
        thread_privada = await obter_ou_criar_thread_privada(ctx.author, ctx.guild)
        
        if not thread_privada:
            await ctx.send("❌ Erro ao criar/acessar seu espaço privado. Tente novamente.", delete_after=10)
            return
        
        embed = discord.Embed(
            title="✅ Espaço Privado Criado!",
            description=f"Acesse: {thread_privada.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🔒 Privacidade Total",
            value="• Apenas você pode ver\n• PIX e Cartão disponíveis\n• Cancelamento via !status",
            inline=False
        )
        embed.set_footer(text="Mensagem deletada em 15s")
        
        await ctx.send(embed=embed, delete_after=15)
        
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        
        if thread_privada.message_count <= 1:
            welcome_embed = discord.Embed(
                title="🎉 Seu Espaço Privado!",
                description="Ambiente privado para gerenciar assinaturas.",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(
                name="🛍️ Comandos:",
                value="• `!planos` - Ver planos\n• `!status` - Gerenciar/cancelar\n• `!plano <id>` - Comprar específico",
                inline=False
            )
            welcome_embed.add_field(
                name="💳 Pagamentos:",
                value="• PIX - Confirmação rápida\n• Cartão - Até 12x sem juros\n• Modalidade única ou mensal",
                inline=False
            )
            
            await thread_privada.send(embed=welcome_embed)
        
    except Exception as e:
        print(f"Erro no comando assinatura: {e}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.command(name="stats")
@commands.has_permissions(administrator=True)
async def estatisticas_bot(ctx):
    """Estatísticas do bot"""
    try:
        db = load_planos_db()
        payments_db = load_payments_db()
        pix_db = load_pix_db()
        posts_db = load_posts_db()
        agora = int(time.time())
        
        planos_ativos = 0
        planos_expirados = 0
        total_arrecadado_cartao = 0
        total_arrecadado_pix = 0
        pagamentos_pendentes = 0
        
        for plano in db:
            fim = plano.get("data_fim", 0)
            if fim > agora:
                planos_ativos += 1
            else:
                planos_expirados += 1
        
        for payment_data in payments_db.values():
            if payment_data["status"] == "approved":
                total_arrecadado_cartao += payment_data.get("amount", 0)
            elif payment_data["status"] == "pending":
                pagamentos_pendentes += 1
        
        for pix_data in pix_db.values():
            if pix_data["status"] == "approved":
                total_arrecadado_pix += pix_data.get("amount", 0)
        
        tipos = {"vendedor": 0, "comprador": 0, "destacar": 0}
        modalidades = {"mensal": 0, "unico": 0}
        
        for plano in db:
            if plano.get("data_fim", 0) > agora:
                tipo = plano.get("tipo", "")
                modalidade = plano.get("modalidade", "mensal")
                if tipo in tipos:
                    tipos[tipo] += 1
                if modalidade in modalidades:
                    modalidades[modalidade] += 1
        
        total_posts_rede = sum(user_data.get("posts_rede", 0) for user_data in posts_db.values())
        total_destaques = sum(user_data.get("destaques_usados", 0) for user_data in posts_db.values())
        
        embed = discord.Embed(
            title="📊 Estatísticas do Sistema",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📈 Planos",
            value=f"**Ativos:** {planos_ativos}\n**Expirados:** {planos_expirados}",
            inline=True
        )
        
        total_arrecadado = total_arrecadado_cartao + total_arrecadado_pix
        embed.add_field(
            name="💰 Financeiro",
            value=f"**Total:** R$ {total_arrecadado:.2f}\n**Cartão:** R$ {total_arrecadado_cartao:.2f}\n**PIX:** R$ {total_arrecadado_pix:.2f}\n**Pendentes:** {pagamentos_pendentes}",
            inline=True
        )
        
        embed.add_field(
            name="🎯 Por Tipo",
            value=f"**Vendedor:** {tipos['vendedor']}\n**Comprador:** {tipos['comprador']}\n**Destacar:** {tipos['destacar']}",
            inline=True
        )
        
        embed.add_field(
            name="💎 Modalidades",
            value=f"**Mensal:** {modalidades['mensal']}\n**Único:** {modalidades['unico']}",
            inline=True
        )
        
        embed.add_field(
            name="📊 Atividade",
            value=f"**Posts rede:** {total_posts_rede}\n**Destaques:** {total_destaques}",
            inline=True
        )
        
        embed.add_field(
            name="🤖 Bot",
            value=f"**Servidores:** {len(bot.guilds)}\n**Usuários:** {len(set(bot.get_all_members()))}",
            inline=True
        )
        
        embed.set_footer(text=f"Última verificação: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erro nas estatísticas: {e}")
        await ctx.send("❌ Erro ao gerar estatísticas.")

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} está online!")
    print(f"📊 Conectado a {len(bot.guilds)} servidor(s)")
    print(f"👥 Alcançando {len(set(bot.get_all_members()))} usuários únicos")
    print(f"💳 Sistema COMPLETO ativo:")
    print("   • Pagamentos PIX e Cartão")
    print("   • Modalidades: Mensal e Única (+50%)")
    print("   • Sistema de cancelamento com taxas")
    print("   • Verificação automática a cada 5min")
    print(f"🏷️ Canais: {CHANNEL_CONFIG}")
    print("🔄 FUNCIONALIDADES PRINCIPAIS:")
    print("   • PIX: Pagamento rápido via código")
    print("   • Cartão: Até 12x sem juros")  
    print("   • Cancelamento: Taxa 100% antes de 2 meses")
    print("   • Cargos: Vendedor/Comprador/Destacar")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
        print("🔄 Verificação automática iniciada")

@bot.event
async def on_command_error(ctx, error):
    """Tratamento de erros"""
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(
            title="❓ Comando não encontrado",
            description=f"Use `!ajuda` para ver comandos disponíveis.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Sem permissão.", delete_after=5)
    
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumento inválido.", delete_after=5)
    
    else:
        print(f"Erro no comando {ctx.command}: {error}")
        await ctx.send("❌ Erro interno. Tente novamente.", delete_after=5)

@bot.event
async def on_guild_join(guild):
    """Quando o bot entra em um servidor novo"""
    print(f"➕ Bot adicionado ao servidor: {guild.name} (ID: {guild.id})")
    
    # Configurar fórum automaticamente
    await garantir_forum_configurado(guild)
    
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="🎉 Sistema de Assinaturas Ativado!",
                description="Bot com pagamentos reais via PIX e Cartão!",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🚀 Começar",
                value="• `!ajuda` - Todos os comandos\n• `!assinatura` - Espaço privado\n• `!planos` - Ver planos disponíveis",
                inline=False
            )
            
            embed.add_field(
                name="💰 Novidades",
                value="• **PIX**: Pagamento instantâneo\n• **Modalidade Única**: +50% do valor, 1 mês\n• **Cancelamento**: Com sistema de taxas",
                inline=False
            )
            
            embed.add_field(
                name="🏷️ Configure os Canais",
                value=f"• `{CHANNEL_CONFIG['rede']}` - Para vendedores\n• `{CHANNEL_CONFIG['recomendacao']}` - Para compradores\n• `{CHANNEL_CONFIG['destaques']}` - Posts destacados",
                inline=False
            )
            
            embed.add_field(
                name="⚡ Sistema Automático",
                value="• Verificação de pagamentos a cada 5min\n• Cargos atribuídos automaticamente\n• Controle de posts por plano",
                inline=False
            )
            
            embed.set_footer(text="Digite !assinatura para começar com privacidade total!")
            
            try:
                await channel.send(embed=embed)
                break
            except discord.Forbidden:
                continue

@bot.event
async def on_member_join(member):
    """Quando um usuário entra no servidor - reatribuir cargos"""
    try:
        db = load_planos_db()
        agora = int(time.time())
        
        for plano in db:
            if (plano["user_id"] == member.id and 
                plano.get("pago", False) and 
                plano.get("data_fim", 0) > agora):
                
                await assign_role_to_member(member, plano["tipo"])
                print(f"Cargo {plano['tipo']} reatribuído para {member.display_name}")
                
    except Exception as e:
        print(f"Erro ao reatribuir cargos para {member.display_name}: {e}")

# ================== INICIALIZAÇÃO ==================
if __name__ == "__main__":
    print("🚀 Iniciando Sistema de Assinaturas Discord...")
    print("=" * 60)
    print("💳 PAGAMENTOS REAIS VIA MERCADO PAGO")
    print("📱 PIX - Pagamento instantâneo")
    print("💳 CARTÃO - Crédito/Débito até 12x")
    print("💎 MODALIDADE ÚNICA - +50% do valor, válido 1 mês")
    print("🗑️ SISTEMA DE CANCELAMENTO - Taxa 100% antes de 2 meses")
    print("🤖 VERIFICAÇÃO AUTOMÁTICA - A cada 5 minutos")
    print("🎯 CARGOS AUTOMÁTICOS - Vendedor/Comprador/Destacar")
    print("=" * 60)
    print(f"🏷️ Canais configurados: {CHANNEL_CONFIG}")
    print("🆕 ATUALIZAÇÕES DOS PLANOS:")
    print("   • Vendedor Verde: Sistema alternado (hoje não, amanhã sim)")
    print("   • Comprador Verde: 2 posts a cada 2 dias")
    print("   • Destacar Vermelho: Destaques ilimitados")
    print("=" * 60)
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if not ML_TOKEN:
        print("❌ ML_TOKEN não encontrado no arquivo .env!")
        exit(1)
    
    if ML_TOKEN.startswith("APP_USR"):
        print("🚨 ATENÇÃO: TOKENS DE PRODUÇÃO - COBRANÇAS REAIS!")
        print("💰 PIX e Cartões serão cobrados de verdade!")
    elif ML_TOKEN.startswith("TEST"):
        print("🧪 TOKENS DE TESTE - Ambiente de desenvolvimento")
        print("🔧 Pagamentos simulados para testes")
    else:
        print("⚠️ Token do Mercado Pago não identificado")
    
    print("=" * 60)
    print("🔄 RECURSOS IMPLEMENTADOS:")
    print("✅ PIX com código QR")
    print("✅ Cartão até 12x sem juros")
    print("✅ Modalidade única (+50%)")
    print("✅ Sistema de cancelamento")
    print("✅ Verificação automática")
    print("✅ Cargos automáticos")
    print("✅ Controle de posts")
    print("✅ Sistema de destaques")
    print("✅ Espaço privado por usuário")
    print("=" * 60)
    
    try:
        carregar_modulos()
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ TOKEN do Discord inválido! Verifique o arquivo .env")
    except discord.HTTPException as e:
        print(f"❌ Erro HTTP: {e}")
    except KeyboardInterrupt:
        print("\n👋 Bot encerrado pelo usuário")
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        print("🔴 Bot desconectado")
import os
import json
import time
import random
import asyncio
import requests
from typing import List, Dict, Any
from datetime import datetime, timedelta
import pytz

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from dotenv import load_dotenv
import mercadopago

# ----------------- CONFIGURAÇÕES -----------------
load_dotenv("arquivo.env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ML_TOKEN = os.getenv("ML_TOKEN")
ML_PUBLIC_KEY = os.getenv("ML_PUBLIC_KEY")

# Inicializar SDK do Mercado Pago
sdk = mercadopago.SDK(ML_TOKEN)

DB_FILE = "planos_ativos.json"
POST_DB = "posts.json"
PAYMENTS_DB = "pagamentos.json"
PIX_DB = "pix_payments.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------- PLANOS ATUALIZADOS COM MODALIDADES -----------------
PLANOS = [
    {"id_plano": 1, "descricao": "Vendedor Vermelho 🔴", "tipo": "vendedor", "dias_post": 1, "preco": 25.00},
    {"id_plano": 2, "descricao": "Vendedor Verde 🟢", "tipo": "vendedor", "dias_post": 1, "alternado": True, "preco": 15.90},
    {"id_plano": 3, "descricao": "Vendedor Azul 🔵", "tipo": "vendedor", "dias_post": 2, "preco": 7.90},
    {"id_plano": 4, "descricao": "Destacar Vermelho 🔴", "tipo": "destacar", "tags": "ilimitado", "preco": 75.00},
    {"id_plano": 5, "descricao": "Destacar Verde 🟢", "tipo": "destacar", "tags": 2, "posts_necessarios": 10, "preco": 27.80},
    {"id_plano": 6, "descricao": "Destacar Azul 🔵", "tipo": "destacar", "tags": 1, "posts_necessarios": 10, "preco": 17.80},
    {"id_plano": 7, "descricao": "Comprador Vermelho 🔴", "tipo": "comprador", "dias_post": 1, "preco": 24.90},
    {"id_plano": 8, "descricao": "Comprador Verde 🟢", "tipo": "comprador", "dias_post": 2, "posts_por_periodo": 2, "preco": 12.00},
    {"id_plano": 9, "descricao": "Comprador Azul 🔵", "tipo": "comprador", "dias_post": 2, "preco": 9.50},
]

# Configurações dos canais
CHANNEL_CONFIG = {
    "rede": "🛒rede",
    "recomendacao": "🌟recomendação-do-caveira",
    "destaques": "💯destaques",
    "forum_assinaturas": "assinar🌟",
    "categoria_assinaturas": "📃🌟Assinaturas"
}

# ================== UTILITÁRIOS JSON ==================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        print(f"Erro ao ler {path}, usando valores padrão")
        return default

def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar {path}: {e}")

def load_planos_db():
    return load_json(DB_FILE, [])

def save_planos_db(data):
    save_json(DB_FILE, data)

def load_payments_db():
    return load_json(PAYMENTS_DB, {})

def save_payments_db(data):
    save_json(PAYMENTS_DB, data)

def load_posts_db():
    return load_json(POST_DB, {})

def save_posts_db(data):
    save_json(POST_DB, data)

def load_pix_db():
    return load_json(PIX_DB, {})

def save_pix_db(data):
    save_json(PIX_DB, data)

# ================== SISTEMA DE FÓRUM PRIVADO ==================
async def obter_ou_criar_thread_privada(user: discord.Member, guild: discord.Guild):
    """Obtém ou cria uma thread privada no fórum de assinaturas para o usuário"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} não encontrada")
            return None
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} não encontrado na categoria")
            return None
        
        if not isinstance(forum_channel, discord.ForumChannel):
            print(f"Canal {CHANNEL_CONFIG['forum_assinaturas']} não é um canal de fórum")
            return None
        
        for thread in forum_channel.threads:
            if thread.name == f"Assinatura - {user.display_name}" or thread.owner_id == user.id:
                return thread
        
        try:
            embed = discord.Embed(
                title=f"🌟 Assinatura Privada - {user.display_name}",
                description="Este é seu espaço privado de assinatura. Apenas você pode ver e interagir aqui.",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="📋 Como usar:",
                value="• Use `!status` para ver seus planos\n• Use `!planos` para comprar novos planos\n• Este chat é totalmente privado",
                inline=False
            )
            embed.set_footer(text="Sistema de Assinaturas Privadas")
            
            thread = await forum_channel.create_thread(
                name=f"Assinatura - {user.display_name}",
                content="",
                embed=embed,
                auto_archive_duration=10080,
                slowmode_delay=0
            )
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            await thread.thread.edit(overwrites=overwrites)
            await thread.thread.add_user(user)
            
            print(f"Thread privada criada para {user.display_name}")
            return thread.thread
            
        except discord.Forbidden:
            print(f"Sem permissão para criar thread no fórum")
            return None
        except Exception as e:
            print(f"Erro ao criar thread: {e}")
            return None
    
    except Exception as e:
        print(f"Erro no sistema de fórum privado: {e}")
        return None

async def garantir_forum_configurado(guild: discord.Guild):
    """Garante que o fórum e categoria estão configurados corretamente"""
    try:
        categoria = discord.utils.get(guild.categories, name=CHANNEL_CONFIG["categoria_assinaturas"])
        if not categoria:
            try:
                categoria = await guild.create_category(CHANNEL_CONFIG["categoria_assinaturas"])
                print(f"Categoria {CHANNEL_CONFIG['categoria_assinaturas']} criada")
            except discord.Forbidden:
                print("Sem permissão para criar categoria")
                return False
        
        forum_channel = discord.utils.get(categoria.channels, name=CHANNEL_CONFIG["forum_assinaturas"])
        if not forum_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False
                    ),
                    guild.me: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        create_public_threads=True,
                        create_private_threads=True,
                        manage_threads=True
                    )
                }
                
                forum_channel = await categoria.create_forum(
                    CHANNEL_CONFIG["forum_assinaturas"],
                    topic="Fórum de assinaturas privadas - cada usuário tem seu espaço individual",
                    overwrites=overwrites,
                    slowmode_delay=60
                )
                print(f"Fórum {CHANNEL_CONFIG['forum_assinaturas']} criado")
            except discord.Forbidden:
                print("Sem permissão para criar fórum")
                return False
            except Exception as e:
                print(f"Erro ao criar fórum: {e}")
                return False
        
        return True
    
    except Exception as e:
        print(f"Erro ao configurar fórum: {e}")
        return False

# ================== SISTEMA DE CANCELAMENTO ==================
def calcular_taxa_cancelamento(data_inicio: int, eh_pagamento_unico: bool = False):
    """Calcula a taxa de cancelamento baseada no tempo desde a compra"""
    agora = int(time.time())
    dias_desde_compra = (agora - data_inicio) // 86400
    
    if dias_desde_compra < 60:  # Menos de 2 meses
        if eh_pagamento_unico:
            return 1.0  # 100% de taxa para pagamento único
        else:
            return 1.0  # 100% de taxa para cancelamento antes de 2 meses
    else:
        return 0.0  # Sem taxa após 2 meses

def pode_cancelar_plano(user_id: int, id_plano: int):
    """Verifica se o usuário pode cancelar um plano específico"""
    db = load_planos_db()
    agora = int(time.time())
    
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["id_plano"] == id_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            
            return True, plano
    
    return False, None

# ================== SISTEMA PIX ==================
def gerar_chave_pix():
    """Gera uma chave PIX única para o pagamento"""
    import uuid
    return str(uuid.uuid4())

def criar_pagamento_pix(plano: dict, user_id: int, username: str, modalidade: str = "mensal"):
    """Cria um pagamento PIX através do Mercado Pago"""
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        # Calcular preço baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5  # 50% a mais
        
        referencia_pix = f"pix_{plano['id_plano']}_user_{user_id}_{int(time.time())}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        payment_data = {
            "transaction_amount": preco_final,
            "description": f"Plano {plano['descricao']} - {modalidade.capitalize()}",
            "payment_method_id": "pix",
            "payer": {
                "email": f"user{user_id}@discord.bot",
                "first_name": nome_usuario,
                "last_name": "Discord",
                "identification": {
                    "type": "CPF",
                    "number": "00000000000"  # CPF fictício para teste
                }
            },
            "external_reference": referencia_pix,
            "notification_url": "https://webhook.site/unique-id",  # Substitua por sua URL de webhook
            "date_of_expiration": (agora + timedelta(minutes=30)).isoformat()
        }
        
        payment_response = sdk.payment().create(payment_data)
        
        if payment_response["status"] == 201:
            payment_info = payment_response["response"]
            
            # Salvar informações do PIX
            pix_db = load_pix_db()
            pix_record = {
                "payment_id": payment_info["id"],
                "user_id": user_id,
                "plano": plano,
                "modalidade": modalidade,
                "amount": preco_final,
                "status": "pending",
                "created_date": payment_info["date_created"],
                "external_reference": referencia_pix,
                "qr_code": payment_info["point_of_interaction"]["transaction_data"]["qr_code"],
                "qr_code_base64": payment_info["point_of_interaction"]["transaction_data"]["qr_code_base64"],
                "ticket_url": payment_info["point_of_interaction"]["transaction_data"]["ticket_url"]
            }
            
            pix_db[str(payment_info["id"])] = pix_record
            save_pix_db(pix_db)
            
            return payment_info, pix_record
        else:
            print(f"Erro ao criar pagamento PIX: {payment_response}")
            return None, None
            
    except Exception as e:
        print(f"Erro ao criar pagamento PIX: {e}")
        return None, None

def verificar_pagamento_pix(payment_id: str):
    """Verifica o status de um pagamento PIX"""
    try:
        payment_response = sdk.payment().get(payment_id)
        
        if payment_response["status"] == 200:
            return payment_response["response"]
        else:
            print(f"Erro ao verificar pagamento PIX: {payment_response}")
            return None
            
    except Exception as e:
        print(f"Erro ao verificar pagamento PIX: {e}")
        return None

# ================== SISTEMA DE POSTS ATUALIZADO ==================
def pode_postar(user_id: int, tipo_plano: str):
    """Verifica se o usuário pode postar baseado no plano dele"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo
    plano_ativo = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == tipo_plano and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_ativo = plano
            break
    
    if not plano_ativo:
        return False, "Você não possui um plano ativo do tipo necessário."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_ativo["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    user_posts = posts_db.get(str(user_id), {})
    ultimo_post = user_posts.get(f"ultimo_post_{tipo_plano}", 0)
    
    # VENDEDOR VERDE: Sistema alternado (hoje não, amanhã sim)
    if plano_info["id_plano"] == 2:  # Vendedor Verde
        if ultimo_post == 0:  # Primeiro post
            return True, plano_ativo
            
        dias_desde_ultimo = (agora - ultimo_post) // 86400
        if dias_desde_ultimo == 0:  # Mesmo dia do último post
            return False, "Você pode postar novamente amanhã (sistema alternado)."
        elif dias_desde_ultimo >= 1:  # 1+ dias depois - pode postar
            return True, plano_ativo
    
    # COMPRADOR VERDE: 2 posts a cada 2 dias
    elif plano_info["id_plano"] == 8:  # Comprador Verde
        posts_por_periodo = plano_info.get("posts_por_periodo", 2)
        periodo = plano_info.get("dias_post", 2) * 86400  # 2 dias em segundos
        
        posts_no_periodo = user_posts.get(f"posts_periodo_{tipo_plano}", {"inicio": 0, "count": 0})
        
        # Se passou o período, resetar contador
        if agora - posts_no_periodo["inicio"] >= periodo:
            posts_no_periodo = {"inicio": agora, "count": 0}
            user_posts[f"posts_periodo_{tipo_plano}"] = posts_no_periodo
            save_posts_db(posts_db)
        
        # Verificar se ainda pode postar no período atual
        if posts_no_periodo["count"] >= posts_por_periodo:
            tempo_restante = periodo - (agora - posts_no_periodo["inicio"])
            horas_restantes = tempo_restante // 3600
            return False, f"Você já fez {posts_por_periodo} posts neste período. Aguarde {horas_restantes} horas."
        
        return True, plano_ativo
    
    # OUTROS PLANOS: Sistema normal por dias
    else:
        dias_necessarios = plano_info.get("dias_post", 1)
        tempo_espera = dias_necessarios * 86400  # dias em segundos
        
        if agora - ultimo_post < tempo_espera:
            horas_restantes = (tempo_espera - (agora - ultimo_post)) // 3600
            return False, f"Você pode postar novamente em {horas_restantes} horas."
        
        return True, plano_ativo

def pode_usar_destaque(user_id: int):
    """Verifica se o usuário pode usar a tag de destaque"""
    db = load_planos_db()
    posts_db = load_posts_db()
    agora = int(time.time())
    
    # Verificar se tem plano ativo de destacar
    plano_destacar = None
    for plano in db:
        if (plano["user_id"] == user_id and 
            plano["tipo"] == "destacar" and 
            plano.get("pago", False) and
            plano.get("data_fim", 0) > agora):
            plano_destacar = plano
            break
    
    if not plano_destacar:
        return False, "Você precisa de um plano de destaque para usar esta tag."
    
    # Buscar dados do plano
    plano_info = next((p for p in PLANOS if p["id_plano"] == plano_destacar["id_plano"]), None)
    if not plano_info:
        return False, "Erro: plano não encontrado."
    
    # PLANO VERMELHO: ILIMITADO
    if plano_info["id_plano"] == 4:  # Destacar Vermelho
        return True, plano_destacar
    
    user_posts = posts_db.get(str(user_id), {})
    
    # Para planos Verde e Azul de destaque, verificar posts na rede
    if "posts_necessarios" in plano_info:
        posts_rede = user_posts.get("posts_rede", 0)
        destaques_usados = user_posts.get("destaques_usados", 0)
        
        # Calcular quantos destaques pode usar
        destaques_disponiveis = (posts_rede // plano_info["posts_necessarios"]) * plano_info["tags"]
        
        if destaques_usados >= destaques_disponiveis:
            posts_faltantes = plano_info["posts_necessarios"] - (posts_rede % plano_info["posts_necessarios"])
            return False, f"Você precisa fazer mais {posts_faltantes} posts na 🛒rede para usar destaque novamente."
    
    return True, plano_destacar

def registrar_post(user_id: int, canal_tipo: str, tem_destaque: bool = False):
    """Registra um post do usuário"""
    posts_db = load_posts_db()
    user_posts = posts_db.get(str(user_id), {})
    agora = int(time.time())
    
    # Registrar último post por tipo
    if canal_tipo == "vendedor":
        user_posts["ultimo_post_vendedor"] = agora
        user_posts["posts_rede"] = user_posts.get("posts_rede", 0) + 1
    elif canal_tipo == "comprador":
        user_posts["ultimo_post_comprador"] = agora
        
        # Para comprador verde, atualizar contador do período
        db = load_planos_db()
        for plano in db:
            if (plano["user_id"] == user_id and 
                plano["tipo"] == "comprador" and 
                plano.get("pago", False) and
                plano.get("data_fim", 0) > agora):
                
                plano_info = next((p for p in PLANOS if p["id_plano"] == plano["id_plano"]), None)
                if plano_info and plano_info["id_plano"] == 8:  # Comprador Verde
                    posts_no_periodo = user_posts.get("posts_periodo_comprador", {"inicio": 0, "count": 0})
                    posts_no_periodo["count"] += 1
                    user_posts["posts_periodo_comprador"] = posts_no_periodo
                break
    
    # Registrar uso de destaque
    if tem_destaque:
        user_posts["destaques_usados"] = user_posts.get("destaques_usados", 0) + 1
    
    posts_db[str(user_id)] = user_posts
    save_posts_db(posts_db)

async def mover_para_destaques(message: discord.Message):
    """Move uma mensagem com tag de destaque para o canal de destaques"""
    try:
        guild = message.guild
        canal_destaques = discord.utils.get(guild.channels, name=CHANNEL_CONFIG["destaques"])
        
        if not canal_destaques:
            print(f"Canal {CHANNEL_CONFIG['destaques']} não encontrado")
            return
        
        embed = discord.Embed(
            title="💯 Post em Destaque",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.set_footer(text=f"Original em #{message.channel.name}")
        embed.timestamp = message.created_at
        
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        
        await canal_destaques.send(embed=embed)
        print(f"Post de {message.author.display_name} movido para destaques")
        
    except Exception as e:
        print(f"Erro ao mover para destaques: {e}")

# ================== MERCADO PAGO CARTÃO ==================
def criar_preferencia_pagamento(plano: dict, user_id: int, username: str, modalidade: str = "mensal"):
    try:
        tz_brasil = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(tz_brasil)
        
        # Calcular preço baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5  # 50% a mais
        
        referencia = f"plano_{plano['id_plano']}_user_{user_id}_{int(time.time())}_{modalidade}"
        nome_usuario = username[:50] if username else "Usuario Discord"
        
        preference_data = {
            "items": [
                {
                    "title": f"Plano {plano['descricao']} - {modalidade.capitalize()}",
                    "quantity": 1,
                    "unit_price": preco_final,
                    "currency_id": "BRL",
                    "description": f"Plano {plano['tipo']} - Discord Bot - {modalidade}"
                }
            ],
            "payer": {
                "name": nome_usuario,
                "surname": "Discord User"
            },
            "payment_methods": {
                "excluded_payment_methods": [],
                "excluded_payment_types": [],
                "installments": 12
            },
            "back_urls": {
                "success": "https://www.cleitodiscord.com/success",
                "failure": "https://www.cleitodiscord.com/failure", 
                "pending": "https://www.cleitodiscord.com/pending"
            },
            "auto_return": "approved",
            "external_reference": referencia,
            "statement_descriptor": "DISCORD_BOT",
            "expires": True,
            "expiration_date_from": agora.isoformat(),
            "expiration_date_to": (agora + timedelta(hours=24)).isoformat()
        }
        
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response["status"] == 201:
            return preference_response["response"]
        else:
            print(f"Erro ao criar preferência: {preference_response}")
            return None
    except Exception as e:
        print(f"Erro ao criar preferência de pagamento: {e}")
        return None

def verificar_pagamento_por_referencia(external_reference):
    try:
        filters = {"external_reference": external_reference}
        search_response = sdk.payment().search(filters)
        
        if search_response["status"] == 200:
            results = search_response["response"]["results"]
            if results:
                return results[0]
        elif search_response["status"] == 429:
            print("Rate limit atingido - aguardando...")
            time.sleep(5)
            return None
        else:
            print(f"Erro na busca de pagamento: {search_response}")
        return None
    except Exception as e:
        print(f"Erro ao buscar pagamento: {e}")
        return None

def ativar_plano_apos_pagamento(user_id: int, plano: dict, modalidade: str = "mensal"):
    try:
        db = load_planos_db()
        
        timestamp = int(time.time())
        
        # Definir duração baseada na modalidade
        if modalidade == "unico":
            duracao = 30 * 86400  # 30 dias para pagamento único
        else:
            duracao = 30 * 86400  # 30 dias para mensal (seria recorrente em produção)
        
        plano_registro = {
            "user_id": user_id,
            "id_plano": plano["id_plano"],
            "descricao": plano["descricao"],
            "tipo": plano["tipo"],
            "pago": True,
            "modalidade": modalidade,
            "data_inicio": timestamp,
            "data_fim": timestamp + duracao
        }
        
        db.append(plano_registro)
        save_planos_db(db)
        return plano_registro
    except Exception as e:
        print(f"Erro ao ativar plano: {e}")
        return None

# ================== ROLES DISCORD ==================
async def ensure_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        try:
            role = await guild.create_role(name=name, color=discord.Color.blue())
            print(f"Cargo '{name}' criado no servidor {guild.name}")
        except discord.Forbidden:
            print(f"Sem permissão para criar cargo: {name}")
            return None
        except Exception as e:
            print(f"Erro ao criar cargo {name}: {e}")
            return None
    return role

async def assign_role_to_member(member: discord.Member, tipo: str):
    try:
        role_name = tipo.capitalize()
        role = await ensure_role(member.guild, role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
            print(f"Cargo '{role_name}' atribuído a {member.display_name}")
            return True
        return True
    except discord.Forbidden:
        print(f"Sem permissão para adicionar cargo a {member.display_name}")
        return False
    except Exception as e:
        print(f"Erro ao atribuir cargo: {e}")
        return False


class EscolherPagamentoView(View):
    def __init__(self, plano, modalidade):
        super().__init__(timeout=300)
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="💳 Cartão/Débito", style=discord.ButtonStyle.primary)
    async def pagamento_cartao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento. Tente novamente em alguns minutos.", ephemeral=True)
                return
            
            preco_final = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
            
            embed = discord.Embed(
                title="💳 Pagamento com Cartão",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {preco_final:.2f}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="💰 Formas de Pagamento Disponíveis:",
                value="• Cartão de Crédito (até 12x)\n• Cartão de Débito",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            embed.set_footer(text=f"ID: {preferencia['id']} - Válido por 24h")
            
            verificar_view = VerificarPagamentoView(preferencia["external_reference"], interaction.user.id, self.plano, self.modalidade)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento cartão: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

    @discord.ui.button(label="📱 PIX", style=discord.ButtonStyle.success)
    async def pagamento_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            payment_info, pix_record = criar_pagamento_pix(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not payment_info or not pix_record:
                await interaction.followup.send("❌ Erro ao criar pagamento PIX. Tente novamente.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📱 Pagamento PIX",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {pix_record['amount']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="📋 Como Pagar:",
                value="1. Copie o código PIX abaixo\n2. Cole no seu app bancário\n3. Confirme o pagamento\n4. Clique em 'Verificar Pagamento'",
                inline=False
            )
            
            embed.add_field(
                name="🔗 Código PIX:",
                value=f"```{pix_record['qr_code']}```",
                inline=False
            )
            
            embed.add_field(name="⏰ Validade", value="30 minutos", inline=True)
            embed.add_field(name="🔍 Status", value="Aguardando pagamento", inline=True)
            
            embed.set_footer(text=f"Payment ID: {payment_info['id']}")
            
            verificar_view = VerificarPagamentoPIXView(str(payment_info['id']), interaction.user.id, self.plano, self.modalidade)
            
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento PIX: {e}")
            await interaction.followup.send("❌ Erro interno. Tente novamente mais tarde.", ephemeral=True)

class VerificarPagamentoView(View):
    def __init__(self, external_reference, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda. Se você acabou de pagar, aguarde alguns minutos.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                preco_pago = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado com sucesso!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor Pago", value=f"R$ {preco_pago:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando. Aguarde alguns minutos e tente novamente.", ephemeral=True)
                
            elif pagamento["status"] == "rejected":
                embed = discord.Embed(
                    title="❌ Pagamento Rejeitado",
                    description="Seu pagamento foi rejeitado. Tente novamente ou use outro método.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}. Continue aguardando ou tente novamente.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)

class VerificarPagamentoPIXView(View):
    def __init__(self, payment_id, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.payment_id = payment_id
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar PIX", style=discord.ButtonStyle.secondary)
    async def verificar_pix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_pix(self.payment_id)
            
            if not pagamento:
                await interaction.followup.send("⏳ Erro ao verificar pagamento. Tente novamente.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano. Contate o suporte.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                # Atualizar status no banco PIX
                pix_db = load_pix_db()
                if self.payment_id in pix_db:
                    pix_db[self.payment_id]["status"] = "approved"
                    save_pix_db(pix_db)
                
                embed = discord.Embed(
                    title="✅ PIX CONFIRMADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado!",
                    color=discord.Color.green()
                )
                embed.add_field(name="📅 Validade", value="30 dias", inline=True)
                embed.add_field(name="💰 Valor", value=f"R$ {pix_db[self.payment_id]['amount']:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ PIX ainda não confirmado. Aguarde alguns minutos após o pagamento.", ephemeral=True)
                
            else:
                await interaction.followup.send(f"Status PIX: {pagamento['status']}. Continue aguardando.", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar PIX: {e}")
            await interaction.followup.send("❌ Erro ao verificar PIX. Tente novamente.", ephemeral=True)

class CancelarPlanoView(View):
    def __init__(self, planos_ativos):
        super().__init__(timeout=300)
        self.planos_ativos = planos_ativos
        
        options = []
        for i, plano in enumerate(planos_ativos):
            modalidade = plano.get("modalidade", "mensal")
            dias_restantes = (plano.get("data_fim", 0) - int(time.time())) // 86400
            
            taxa = calcular_taxa_cancelamento(plano.get("data_inicio", 0), modalidade == "unico")
            taxa_texto = f"Taxa: {int(taxa*100)}%" if taxa > 0 else "Sem taxa"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} ({modalidade})",
                value=str(i),
                description=f"{dias_restantes} dias restantes - {taxa_texto}",
                emoji="🔴" if taxa > 0 else "🟢"
            ))
        
        if options:
            self.select = discord.ui.Select(
                placeholder="Escolha o plano para cancelar...",
                options=options[:25],
                min_values=1,
                max_values=1
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_index = int(self.select.values[0])
        plano_selecionado = self.planos_ativos[selected_index]
        
        modalidade = plano_selecionado.get("modalidade", "mensal")
        taxa = calcular_taxa_cancelamento(plano_selecionado.get("data_inicio", 0), modalidade == "unico")
        dias_desde_compra = (int(time.time()) - plano_selecionado.get("data_inicio", 0)) // 86400
        
        embed = discord.Embed(
            title="⚠️ Confirmação de Cancelamento",
            description=f"**Plano:** {plano_selecionado['descricao']}\n**Modalidade:** {modalidade.capitalize()}",
            color=discord.Color.orange()
        )
        
        if taxa > 0:
            embed.add_field(
                name="💰 Taxa de Cancelamento",
                value=f"**{int(taxa*100)}%** do valor pago\n*Comprado há {dias_desde_compra} dias*",
                inline=False
            )
            embed.add_field(
                name="📋 Motivo da Taxa:",
                value="• Cancelamento antes de 2 meses" + (" (Pagamento único)" if modalidade == "unico" else ""),
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Sem Taxa",
                value="Cancelamento após 2 meses da compra",
                inline=False
            )
        
        embed.add_field(
            name="⚠️ ATENÇÃO:",
            value="• Plano será cancelado imediatamente\n• Acesso será removido\n• Não há reembolso além da taxa",
            inline=False
        )
        
        view = ConfirmarCancelamentoView(plano_selecionado)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmarCancelamentoView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="✅ Confirmar Cancelamento", style=discord.ButtonStyle.danger)
    async def confirmar_cancelamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            db = load_planos_db()
            
            # Remover o plano do banco de dados
            db = [p for p in db if not (p["user_id"] == self.plano["user_id"] and p["id_plano"] == self.plano["id_plano"])]
            save_planos_db(db)
            
            # Remover cargo do usuário
            guild_member = interaction.guild.get_member(self.plano["user_id"])
            if guild_member:
                role_name = self.plano["tipo"].capitalize()
                role = discord.utils.get(guild_member.guild.roles, name=role_name)
                if role and role in guild_member.roles:
                    await guild_member.remove_roles(role)
            
            modalidade = self.plano.get("modalidade", "mensal")
            taxa = calcular_taxa_cancelamento(self.plano.get("data_inicio", 0), modalidade == "unico")
            
            embed = discord.Embed(
                title="✅ Plano Cancelado",
                description=f"Seu plano **{self.plano['descricao']}** foi cancelado com sucesso.",
                color=discord.Color.red()
            )
            
            if taxa > 0:
                embed.add_field(
                    name="💰 Taxa Aplicada",
                    value=f"{int(taxa*100)}% conforme política de cancelamento",
                    inline=False
                )
            
            embed.add_field(
                name="📋 Informações:",
                value="• Acesso removido imediatamente\n• Cargo Discord removido\n• Para reativar, faça uma nova compra",
                inline=False
            )
            
            for item in self.children:
                item.disabled = True
            
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            
        except Exception as e:
            print(f"Erro ao cancelar plano: {e}")
            await interaction.response.send_message("❌ Erro ao cancelar plano. Tente novamente.", ephemeral=True)

    @discord.ui.button(label="❌ Manter Plano", style=discord.ButtonStyle.secondary)
    async def manter_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ Cancelamento Abortado",
            description="Seu plano foi mantido e continua ativo.",
            color=discord.Color.green()
        )
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        try:
            db = load_planos_db()
            agora = int(time.time())
            
            for plano_ativo in db:
                if (plano_ativo["user_id"] == user_id and 
                    plano_ativo["tipo"] == self.plano["tipo"] and 
                    plano_ativo.get("pago", False) and
                    plano_ativo.get("data_fim", 0) > agora):
                    await interaction.response.send_message(
                        f"❌ Você já possui um plano ativo do tipo **{self.plano['tipo']}**!", 
                        ephemeral=True
                    )
                    return
            
            embed = discord.Embed(
                title="🛍️ Escolha a Modalidade",
                description=f"**Plano:** {self.plano['descricao']}\n**Tipo:** {self.plano['tipo'].capitalize()}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="💰 Mensal",
                value=f"R$ {self.plano['preco']:.2f}/mês\n✅ Cancelamento flexível",
                inline=True
            )
            
            embed.add_field(
                name="💎 Pagar 1 Vez",
                value=f"R$ {self.plano['preco'] * 1.5:.2f} (+50%)\n⚠️ Taxa de cancelamento",
                inline=True
            )
            
            view = EscolherModalidadeView(self.plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        except Exception as e:
            print(f"Erro na compra: {e}")
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)

class SelecionarPlanoView(View):
    def __init__(self):
        super().__init__(timeout=300)
        
        options = []
        for plano in PLANOS:
            emoji = "🔴" if "Vermelho" in plano["descricao"] else "🟢" if "Verde" in plano["descricao"] else "🔵"
            
            desc = f"Tipo: {plano['tipo'].capitalize()}"
            if plano["id_plano"] == 2:
                desc += " - Alternado"
            elif plano["id_plano"] == 4:
                desc += " - Ilimitado"
            elif plano["id_plano"] == 8:
                desc += " - 2 posts/2 dias"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} - R$ {plano['preco']:.2f}",
                value=str(plano["id_plano"]),
                emoji=emoji,
                description=desc
            ))
        
        self.select = discord.ui.Select(
            placeholder="Escolha um plano...",
            options=options[:25],
            min_values=1,
            max_values=1
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        selected_id = int(self.select.values[0])
        plano = next((p for p in PLANOS if p["id_plano"] == selected_id), None)
        
        if plano:
            embed = discord.Embed(
                title=f"💰 {plano['descricao']}",
                description=f"**Preço:** R$ {plano['preco']:.2f} (mensal)\n**Tipo:** {plano['tipo'].capitalize()}",
                color=discord.Color.green()
            )
            
            if plano["id_plano"] == 2:
                embed.add_field(name="📅 Postagem", value="Alternada (hoje não, amanhã sim)", inline=True)
            elif plano["id_plano"] == 8:
                embed.add_field(name="📅 Postagem", value="2 posts a cada 2 dias", inline=True)
            elif "dias_post" in plano:
                if plano["dias_post"] == 1:
                    embed.add_field(name="📅 Postagem", value="Diária", inline=True)
                else:
                    embed.add_field(name="📅 Postagem", value=f"A cada {plano['dias_post']} dias", inline=True)
            
            if "tags" in plano:
                if plano["tags"] == "ilimitado":
                    embed.add_field(name="🏷️ Destaques", value="Ilimitados", inline=True)
                elif "posts_necessarios" in plano:
                    embed.add_field(name="🏷️ Destaques", value=f"{plano['tags']} a cada {plano['posts_necessarios']} posts", inline=True)
                else:
                    embed.add_field(name="🏷️ Tags", value=str(plano["tags"]), inline=True)
            
            embed.add_field(name="⏰ Duração", value="30 dias", inline=True)
            embed.set_footer(text="Escolha entre modalidade mensal ou pagamento único")
            
            view = ComprarViewCompleta(plano)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # ================== CORREÇÕES - ADICIONAR ESTAS FUNÇÕES ==================

# 1. CORRIGIR FUNÇÃO DE CARGOS - SUBSTITUIR A EXISTENTE
async def assign_role_to_member(member: discord.Member, tipo: str):
    """VERSÃO CORRIGIDA - USA CARGOS EXISTENTES"""
    try:
        role_name = tipo.capitalize()  # vendedor -> Vendedor
        
        # BUSCAR cargo existente no servidor
        role = discord.utils.get(member.guild.roles, name=role_name)
        
        if not role:
            print(f"❌ Cargo '{role_name}' não encontrado no servidor")
            return False
        
        if role not in member.roles:
            await member.add_roles(role)
            print(f"✅ Cargo '{role_name}' atribuído a {member.display_name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao atribuir cargo: {e}")
        return False

# 2. NOVA VIEW PARA MODALIDADES (CORRIGIR BOTÃO "PAGAR 1 VEZ")
# ================== CORREÇÕES PRINCIPAIS ==================

# 1. ERRO NO BOTÃO "PAGAR 1 VEZ" - Typo no ephemeral
class EscolherModalidadeView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Mensal", style=discord.ButtonStyle.green)
    async def modalidade_mensal(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=f"💰 Plano Mensal",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {self.plano['preco']:.2f}/mês",
            color=discord.Color.green()
        )
        embed.add_field(name="✅ Vantagens", value="• Cancelamento após 2 meses sem taxa", inline=False)
        
        view = EscolherPagamentoView(self.plano, "mensal")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="💎 Pagar 1 Vez (+50%)", style=discord.ButtonStyle.blurple)
    async def modalidade_unica(self, interaction: discord.Interaction, button: discord.ui.Button):
        preco_unico = self.plano['preco'] * 1.5
        embed = discord.Embed(
            title=f"💎 Pagamento Único",
            description=f"**Plano:** {self.plano['descricao']}\n**Preço:** R$ {preco_unico:.2f} (única vez)",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="⚠️ Taxa de Cancelamento",
            value="• Antes de 2 meses: **100% de taxa**\n• Válido por 30 dias",
            inline=False
        )
        
        view = EscolherPagamentoView(self.plano, "unico")
        # ERRO ESTAVA AQUI: ephemeal -> ephemeral
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 2. FUNÇÃO DE SALVAR PAGAMENTO CARTÃO CORRIGIDA
def salvar_preferencia_pendente(preference_data, user_id, plano, modalidade="mensal"):
    try:
        payments_db = load_payments_db()
        
        # Calcular preço final baseado na modalidade
        preco_final = plano["preco"]
        if modalidade == "unico":
            preco_final = plano["preco"] * 1.5
        
        payment_record = {
            "preference_id": preference_data["id"],
            "user_id": user_id,
            "plano": plano,
            "modalidade": modalidade,  # ADICIONAR modalidade
            "amount": preco_final,     # USAR preço correto
            "status": "pending",
            "created_date": preference_data["date_created"],
            "checkout_link": preference_data["init_point"],
            "external_reference": preference_data.get("external_reference")
        }
        
        payments_db[str(preference_data["id"])] = payment_record
        save_payments_db(payments_db)
        return payment_record
    except Exception as e:
        print(f"Erro ao salvar preferência pendente: {e}")
        return None

# 3. VIEW DE PAGAMENTO CORRIGIDA
class EscolherPagamentoView(View):
    def __init__(self, plano, modalidade):
        super().__init__(timeout=300)
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="💳 Cartão/Débito", style=discord.ButtonStyle.primary)
    async def pagamento_cartao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            preferencia = criar_preferencia_pagamento(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not preferencia:
                await interaction.followup.send("❌ Erro ao criar link de pagamento.", ephemeral=True)
                return
            
            # SALVAR COM MODALIDADE
            payment_record = salvar_preferencia_pendente(preferencia, interaction.user.id, self.plano, self.modalidade)
            
            preco_final = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
            
            embed = discord.Embed(
                title="💳 Pagamento com Cartão",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {preco_final:.2f}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="🔗 Link para Pagamento:",
                value=f"[**CLIQUE AQUI PARA PAGAR**]({preferencia['init_point']})",
                inline=False
            )
            
            verificar_view = VerificarPagamentoView(preferencia["external_reference"], interaction.user.id, self.plano, self.modalidade)
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento cartão: {e}")
            await interaction.followup.send("❌ Erro interno.", ephemeral=True)

    @discord.ui.button(label="📱 PIX", style=discord.ButtonStyle.success)
    async def pagamento_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            payment_info, pix_record = criar_pagamento_pix(self.plano, interaction.user.id, interaction.user.display_name, self.modalidade)
            
            if not payment_info or not pix_record:
                await interaction.followup.send("❌ Erro ao criar pagamento PIX.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📱 Pagamento PIX",
                description=f"**Plano:** {self.plano['descricao']}\n**Modalidade:** {self.modalidade.capitalize()}\n**Valor:** R$ {pix_record['amount']:.2f}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="🔗 Código PIX:",
                value=f"```{pix_record['qr_code']}```",
                inline=False
            )
            
            verificar_view = VerificarPagamentoPIXView(str(payment_info['id']), interaction.user.id, self.plano, self.modalidade)
            await interaction.followup.send(embed=embed, view=verificar_view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no pagamento PIX: {e}")
            await interaction.followup.send("❌ Erro interno PIX.", ephemeral=True)

# 4. VERIFICAÇÃO DE PAGAMENTO CORRIGIDA
class VerificarPagamentoView(View):
    def __init__(self, external_reference, user_id, plano, modalidade):
        super().__init__(timeout=1800)
        self.external_reference = external_reference
        self.user_id = user_id
        self.plano = plano
        self.modalidade = modalidade

    @discord.ui.button(label="🔄 Verificar Pagamento", style=discord.ButtonStyle.secondary)
    async def verificar_pagamento_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            pagamento = verificar_pagamento_por_referencia(self.external_reference)
            
            if not pagamento:
                await interaction.followup.send("⏳ Nenhum pagamento encontrado ainda.", ephemeral=True)
                return
            
            if pagamento["status"] == "approved":
                plano_ativado = ativar_plano_apos_pagamento(self.user_id, self.plano, self.modalidade)
                
                if not plano_ativado:
                    await interaction.followup.send("❌ Erro ao ativar plano.", ephemeral=True)
                    return
                
                guild_member = interaction.guild.get_member(self.user_id)
                if guild_member:
                    await assign_role_to_member(guild_member, self.plano["tipo"])
                
                # ATUALIZAR STATUS NO BANCO
                payments_db = load_payments_db()
                for payment_id, payment_data in payments_db.items():
                    if payment_data.get("external_reference") == self.external_reference:
                        payment_data["status"] = "approved"
                        save_payments_db(payments_db)
                        break
                
                preco_pago = self.plano['preco'] if self.modalidade == "mensal" else self.plano['preco'] * 1.5
                
                embed = discord.Embed(
                    title="✅ PAGAMENTO APROVADO!",
                    description=f"Seu plano **{self.plano['descricao']}** foi ativado!",
                    color=discord.Color.green()
                )
                embed.add_field(name="💰 Valor", value=f"R$ {preco_pago:.2f}", inline=True)
                embed.add_field(name="🎯 Modalidade", value=self.modalidade.capitalize(), inline=True)
                
                for item in self.children:
                    item.disabled = True
                
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
                
            elif pagamento["status"] == "pending":
                await interaction.followup.send("⏳ Pagamento ainda processando.", ephemeral=True)
            else:
                await interaction.followup.send(f"Status: {pagamento['status']}", ephemeral=True)
        
        except Exception as e:
            print(f"Erro ao verificar pagamento: {e}")
            await interaction.followup.send("❌ Erro ao verificar pagamento.", ephemeral=True)

# 5. SISTEMA DE CANCELAMENTO CORRIGIDO
class CancelarPlanoView(View):
    def __init__(self, planos_ativos):
        super().__init__(timeout=300)
        self.planos_ativos = planos_ativos
        
        if not planos_ativos:
            return
        
        options = []
        for i, plano in enumerate(planos_ativos):
            modalidade = plano.get("modalidade", "mensal")
            dias_restantes = (plano.get("data_fim", 0) - int(time.time())) // 86400
            
            taxa = calcular_taxa_cancelamento(plano.get("data_inicio", 0), modalidade == "unico")
            taxa_texto = f"Taxa: {int(taxa*100)}%" if taxa > 0 else "Sem taxa"
            
            options.append(discord.SelectOption(
                label=f"{plano['descricao']} ({modalidade})",
                value=str(i),
                description=f"{dias_restantes} dias - {taxa_texto}",
                emoji="🔴" if taxa > 0 else "🟢"
            ))
        
        if options:
            self.select = discord.ui.Select(
                placeholder="Escolha o plano para cancelar...",
                options=options[:25]
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)
    
    async def select_callback(self, interaction: discord.Interaction):
        try:
            selected_index = int(self.select.values[0])
            plano_selecionado = self.planos_ativos[selected_index]
            
            modalidade = plano_selecionado.get("modalidade", "mensal")
            taxa = calcular_taxa_cancelamento(plano_selecionado.get("data_inicio", 0), modalidade == "unico")
            
            embed = discord.Embed(
                title="⚠️ Confirmação de Cancelamento",
                description=f"**Plano:** {plano_selecionado['descricao']}\n**Modalidade:** {modalidade.capitalize()}",
                color=discord.Color.orange()
            )
            
            if taxa > 0:
                embed.add_field(
                    name="💰 Taxa de Cancelamento",
                    value=f"**{int(taxa*100)}%** do valor pago",
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Sem Taxa",
                    value="Cancelamento após 2 meses da compra",
                    inline=False
                )
            
            view = ConfirmarCancelamentoView(plano_selecionado)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            print(f"Erro no select callback: {e}")
            await interaction.response.send_message("❌ Erro ao processar seleção.", ephemeral=True)

class ConfirmarCancelamentoView(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="✅ Confirmar Cancelamento", style=discord.ButtonStyle.danger)
    async def confirmar_cancelamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            db = load_planos_db()
            
            # REMOVER PLANO CORRETAMENTE
            db_filtrado = []
            plano_removido = False
            
            for p in db:
                if (p["user_id"] == self.plano["user_id"] and 
                    p["id_plano"] == self.plano["id_plano"] and
                    p.get("data_inicio") == self.plano.get("data_inicio")):
                    plano_removido = True
                    continue
                db_filtrado.append(p)
            
            if not plano_removido:
                await interaction.response.send_message("❌ Plano não encontrado.", ephemeral=True)
                return
            
            save_planos_db(db_filtrado)
            
            # REMOVER CARGO
            guild_member = interaction.guild.get_member(self.plano["user_id"])
            if guild_member:
                role_name = self.plano["tipo"].capitalize()
                role = discord.utils.get(guild_member.guild.roles, name=role_name)
                if role and role in guild_member.roles:
                    await guild_member.remove_roles(role)
            
            embed = discord.Embed(
                title="✅ Plano Cancelado",
                description=f"Seu plano **{self.plano['descricao']}** foi cancelado.",
                color=discord.Color.red()
            )
            
            for item in self.children:
                item.disabled = True
            
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            
        except Exception as e:
            print(f"Erro ao cancelar plano: {e}")
            await interaction.response.send_message("❌ Erro ao cancelar plano.", ephemeral=True)

    @discord.ui.button(label="❌ Manter Plano", style=discord.ButtonStyle.secondary)
    async def manter_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ Cancelamento Abortado",
            description="Seu plano foi mantido e continua ativo.",
            color=discord.Color.green()
        )
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

# 6. VERIFICAÇÃO AUTOMÁTICA CORRIGIDA
@tasks.loop(minutes=5)
async def verificar_pagamentos_automatico():
    """Verifica pagamentos pendentes automaticamente"""
    await bot.wait_until_ready()
    
    try:
        # Verificar pagamentos de cartão
        payments_db = load_payments_db()
        if payments_db:
            for payment_id, payment_data in payments_db.items():
                if payment_data["status"] == "pending":
                    external_ref = payment_data.get("external_reference")
                    if external_ref:
                        pagamento_atual = verificar_pagamento_por_referencia(external_ref)
                        
                        if pagamento_atual and pagamento_atual["status"] == "approved":
                            user_id = payment_data["user_id"]
                            plano = payment_data["plano"]
                            modalidade = payment_data.get("modalidade", "mensal")  # PEGAR MODALIDADE
                            
                            plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                            
                            if plano_ativado:
                                # NOTIFICAR USUÁRIO E ATRIBUIR CARGO
                                for guild in bot.guilds:
                                    member = guild.get_member(user_id)
                                    if member:
                                        await assign_role_to_member(member, plano["tipo"])
                                        break
                                
                                payments_db[payment_id]["status"] = "approved"
                                save_payments_db(payments_db)
                                
                                print(f"✅ Plano {plano['descricao']} ativado automaticamente para usuário {user_id}")
        
        # Verificar pagamentos PIX
        pix_db = load_pix_db()
        if pix_db:
            for payment_id, pix_data in pix_db.items():
                if pix_data["status"] == "pending":
                    pagamento_pix = verificar_pagamento_pix(payment_id)
                    
                    if pagamento_pix and pagamento_pix["status"] == "approved":
                        user_id = pix_data["user_id"]
                        plano = pix_data["plano"]
                        modalidade = pix_data["modalidade"]
                        
                        plano_ativado = ativar_plano_apos_pagamento(user_id, plano, modalidade)
                        
                        if plano_ativado:
                            for guild in bot.guilds:
                                member = guild.get_member(user_id)
                                if member:
                                    await assign_role_to_member(member, plano["tipo"])
                                    break
                            
                            pix_db[payment_id]["status"] = "approved"
                            save_pix_db(pix_db)
                            
                            print(f"✅ Plano PIX {plano['descricao']} ativado automaticamente")
    
    except Exception as e:
        print(f"Erro na verificação automática: {e}")

# 7. COMANDO STATUS COM CANCELAMENTO
@bot.command(name="status")
async def status_usuario(ctx):
    """Mostra status dos planos do usuário com opção de cancelamento"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        
        embed = discord.Embed(
            title=f"📊 Meus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_ativos = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                fim = plano.get("data_fim", agora)
                if fim > agora:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            ativo_text = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                ativo_text += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=ativo_text, inline=False)
            
            # BOTÃO DE CANCELAMENTO
            view = View(timeout=300)
            cancelar_btn = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Você não pode usar este botão.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_ativos)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha o plano que deseja cancelar:",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            cancelar_btn.callback = cancelar_callback
            view.add_item(cancelar_btn)
        else:
            embed.description = "Nenhum plano ativo encontrado."
            view = None
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        print(f"Erro ao mostrar status: {e}")
        await ctx.send("❌ Erro ao verificar status.")

# 3. CORRIGIR VIEW DE COMPRA PARA MOSTRAR MODALIDADES
class ComprarViewCompleta(View):
    def __init__(self, plano):
        super().__init__(timeout=300)
        self.plano = plano

    @discord.ui.button(label="💰 Comprar Plano", style=discord.ButtonStyle.green)
    async def comprar_plano(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        db = load_planos_db()
        agora = int(time.time())
        
        # Verificar se já tem plano ativo do mesmo tipo
        for plano_ativo in db:
            if (plano_ativo["user_id"] == user_id and 
                plano_ativo["tipo"] == self.plano["tipo"] and 
                plano_ativo.get("pago", False) and
                plano_ativo.get("data_fim", 0) > agora):
                await interaction.response.send_message(
                    f"❌ Você já possui um plano **{self.plano['tipo']}** ativo!", 
                    ephemeral=True
                )
                return
        
        # Mostrar opções de modalidade
        embed = discord.Embed(
            title="🛍️ Escolha a Modalidade",
            description=f"**Plano:** {self.plano['descricao']}",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="💰 Mensal",
            value=f"R$ {self.plano['preco']:.2f}/mês",
            inline=True
        )
        embed.add_field(
            name="💎 Única (+50%)",
            value=f"R$ {self.plano['preco'] * 1.5:.2f}",
            inline=True
        )
        
        view = EscolherModalidadeView(self.plano)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 4. STATUS AUTOMÁTICO EM CANAL ESPECÍFICO
async def enviar_status_automatico(guild: discord.Guild):
    """Envia status em canal específico automaticamente"""
    try:
        canal_status = discord.utils.get(guild.channels, name="status-de-plano")
        
        if not canal_status:
            print("Canal 'status-de-plano' não encontrado")
            return
        
        # Limpar mensagens antigas
        try:
            async for message in canal_status.history(limit=100):
                if message.author == bot.user:
                    await message.delete()
        except:
            pass
        
        db = load_planos_db()
        agora = int(time.time())
        
        embed = discord.Embed(
            title="📊 Status Geral de Planos",
            description="Atualizações automáticas dos planos ativos",
            color=discord.Color.blue()
        )
        
        planos_ativos = 0
        usuarios_ativos = set()
        
        for plano in db:
            if plano.get("pago", False) and plano.get("data_fim", 0) > agora:
                planos_ativos += 1
                usuarios_ativos.add(plano["user_id"])
        
        embed.add_field(name="📈 Planos Ativos", value=str(planos_ativos), inline=True)
        embed.add_field(name="👥 Usuários com Plano", value=str(len(usuarios_ativos)), inline=True)
        embed.add_field(name="🔄 Última Atualização", value="Agora", inline=True)
        
        embed.set_footer(text="Use !status para ver seus planos individuais")
        
        await canal_status.send(embed=embed)
        
    except Exception as e:
        print(f"Erro no status automático: {e}")

# 5. COMANDO STATUS INTEGRADO
@bot.command(name="status")
async def status_integrado(ctx):
    """Status com integração ao canal específico"""
    try:
        user_id = ctx.author.id
        db = load_planos_db()
        
        embed = discord.Embed(
            title=f"📊 Seus Planos - {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        agora = int(time.time())
        planos_ativos = []
        
        for plano in db:
            if plano["user_id"] == user_id and plano.get("pago", False):
                fim = plano.get("data_fim", agora)
                if fim > agora:
                    planos_ativos.append(plano)
        
        if planos_ativos:
            texto_planos = ""
            for plano in planos_ativos:
                fim = plano.get("data_fim", agora)
                dias_restantes = (fim - agora) // 86400
                modalidade = plano.get("modalidade", "mensal")
                texto_planos += f"• **{plano['descricao']}** ({modalidade})\n  📅 {dias_restantes} dias restantes\n\n"
            
            embed.add_field(name="✅ Planos Ativos", value=texto_planos, inline=False)
            
            # Botão cancelar só se tem planos
            view = View(timeout=300)
            btn_cancelar = discord.ui.Button(label="🗑️ Cancelar Plano", style=discord.ButtonStyle.danger)
            
            async def cancelar_callback(interaction):
                if interaction.user.id != user_id:
                    await interaction.response.send_message("❌ Não é seu plano.", ephemeral=True)
                    return
                
                view_cancelar = CancelarPlanoView(planos_ativos)
                embed_cancelar = discord.Embed(
                    title="🗑️ Cancelar Plano",
                    description="Escolha qual plano cancelar:",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed_cancelar, view=view_cancelar, ephemeral=True)
            
            btn_cancelar.callback = cancelar_callback
            view.add_item(btn_cancelar)
        else:
            embed.description = "Nenhum plano ativo."
            view = None
        
        # Tentar enviar no canal status-de-plano também
        try:
            canal_status = discord.utils.get(ctx.guild.channels, name="status-de-plano")
            if canal_status:
                embed_canal = embed.copy()
                embed_canal.set_footer(text=f"Status solicitado por {ctx.author.display_name}")
                await canal_status.send(embed=embed_canal)
        except:
            pass
        
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        await ctx.send("❌ Erro ao verificar status.")

# 6. TASK PARA ATUALIZAR STATUS AUTOMÁTICO
@tasks.loop(hours=6)  # Atualiza a cada 6 horas
async def atualizar_status_automatico():
    """Atualiza status no canal automaticamente"""
    await bot.wait_until_ready()
    
    for guild in bot.guilds:
        await enviar_status_automatico(guild)

# 7. INICIAR TASK QUANDO BOT FICAR ONLINE
@bot.event
async def on_ready():
    print(f"🤖 {bot.user} online!")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
    
    if not atualizar_status_automatico.is_running():
        atualizar_status_automatico.start()
    
    # Enviar status inicial em todos os servidores
    for guild in bot.guilds:
        await enviar_status_automatico(guild)
def carregar_modulos():
    pasta_modulos = "modulos"
    
    if not os.path.exists(pasta_modulos):
        os.makedirs(pasta_modulos)
        return
    
    import builtins
    builtins.bot = bot
    builtins.load_planos_db = load_planos_db
    builtins.save_planos_db = save_planos_db
    builtins.PLANOS = PLANOS
    builtins.discord = discord
    builtins.commands = commands
    builtins.time = time
    
    for arquivo in os.listdir(pasta_modulos):
        if arquivo.endswith('.py'):
            nome_modulo = arquivo[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    nome_modulo, 
                    os.path.join(pasta_modulos, arquivo)
                )
                modulo = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modulo)
                print(f"Módulo '{nome_modulo}' carregado")
            except Exception as e:
                print(f"Erro no módulo '{nome_modulo}': {e}")
def carregar_modulos():
    pasta_modulos = "modulos"
    
    if not os.path.exists(pasta_modulos):
        os.makedirs(pasta_modulos)
        return
    
    import builtins
    builtins.bot = bot
    builtins.load_planos_db = load_planos_db
    builtins.save_planos_db = save_planos_db
    builtins.PLANOS = PLANOS
    builtins.discord = discord
    builtins.commands = commands
    builtins.time = time
    
    for arquivo in os.listdir(pasta_modulos):
        if arquivo.endswith('.py'):
            nome_modulo = arquivo[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    nome_modulo, 
                    os.path.join(pasta_modulos, arquivo)
                )
                modulo = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modulo)
                print(f"✅ Módulo '{nome_modulo}' carregado")
            except Exception as e:
                print(f"❌ Erro no módulo '{nome_modulo}': {e}")
@bot.command(name="modulo_teste")
async def teste_modulo(ctx):
    await ctx.send("Módulo funcionando!")
 # 7. INICIAR TASK QUANDO BOT FICAR ONLINE

@bot.event
async def on_ready():
    print(f"🤖 {bot.user} online!")
    
    if not verificar_pagamentos_automatico.is_running():
        verificar_pagamentos_automatico.start()
    
    if not atualizar_status_automatico.is_running():
        atualizar_status_automatico.start()
    
    # Enviar status inicial em todos os servidores
    for guild in bot.guilds:
        await enviar_status_automatico(guild)

def carregar_modulos():
    "Carrega automaticamente todos os módulos da pasta 'modulos'"""
    pasta_modulos = "modulos"
    
    if not os.path.exists(pasta_modulos):
        os.makedirs(pasta_modulos)
        print(f"Pasta '{pasta_modulos}' criada")
        return
    
    # Fazer as funções e variáveis principais disponíveis globalmente
    import builtins
    builtins.bot = bot
    builtins.PLANOS = PLANOS
    builtins.CHANNEL_CONFIG = CHANNEL_CONFIG
    builtins.load_planos_db = load_planos_db
    builtins.save_planos_db = save_planos_db
    builtins.load_posts_db = load_posts_db
    builtins.save_posts_db = save_posts_db
    builtins.load_payments_db = load_payments_db
    builtins.save_payments_db = save_payments_db
    builtins.load_pix_db = load_pix_db
    builtins.save_pix_db = save_pix_db
    builtins.assign_role_to_member = assign_role_to_member
    builtins.ativar_plano_apos_pagamento = ativar_plano_apos_pagamento
    builtins.time = time
    builtins.discord = discord
    builtins.commands = commands
    
    # Carregar todos os arquivos .py da pasta modulos
    for arquivo in os.listdir(pasta_modulos):
        if arquivo.endswith('.py') and not arquivo.startswith('_'):
            nome_modulo = arquivo[:-3]  # Remove .py
            try:
                spec = importlib.util.spec_from_file_location(
                    nome_modulo, 
                    os.path.join(pasta_modulos, arquivo)
                )
                modulo = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modulo)
                print(f"✅ Módulo '{nome_modulo}' carregado com sucesso")
                
            except Exception as e:
                print(f"❌ Erro ao carregar módulo '{nome_modulo}': {e}")
import codigo2bot.py   # importa o outro arquivo

print("bot principal iniciou")

codigo2bot.ola()    # chama função do codigo2bot
