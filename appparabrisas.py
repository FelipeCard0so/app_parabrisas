from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFProtect
import sqlite3
import re
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ==================================================
# CONFIGURAÇÃO
# ==================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave-local-dev')
csrf = CSRFProtect(app)

DB = "database.db"


# ==================================================
# BANCO DE DADOS
# ==================================================

def criar_banco():

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS veiculos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        marca TEXT,
        modelo TEXT,
        ano TEXT,
        original REAL,
        paralelo REAL,
        data_atualizacao TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS consultas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        marca TEXT,
        modelo TEXT,
        ano TEXT,
        original REAL,
        paralelo REAL,
        media REAL,
        categoria TEXT,
        percentual REAL,
        avarias INTEGER,
        valor_final REAL,
        data_consulta TEXT
    )
    """)

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM veiculos")
    total = cursor.fetchone()[0]

    if total == 0:
        veiculos_teste = [
            ("Chevrolet", "Onix", "2022", 1700, 1100, datetime.now().strftime("%d/%m/%Y")),
            ("Fiat",      "Argo", "2022", 1800, 1200, datetime.now().strftime("%d/%m/%Y")),
            ("Hyundai",   "HB20", "2023", 1900, 1300, datetime.now().strftime("%d/%m/%Y")),
            ("BMW",       "X3",   "2022", 7000, 2800, datetime.now().strftime("%d/%m/%Y")),
        ]
        cursor.executemany("""
        INSERT INTO veiculos (marca, modelo, ano, original, paralelo, data_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?)
        """, veiculos_teste)
        conn.commit()
        logger.info("Banco criado com dados iniciais.")

    conn.close()


# ==================================================
# ✅ INICIALIZA O BANCO — RODA COM GUNICORN TAMBÉM
# ==================================================

criar_banco()


# ==================================================
# BUSCA NO BANCO LOCAL
# ==================================================

def buscar_veiculo(marca, modelo, ano):
    try:
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()
        cursor.execute("""
        SELECT original, paralelo, data_atualizacao
        FROM veiculos
        WHERE LOWER(marca) = LOWER(?)
          AND LOWER(modelo) = LOWER(?)
          AND ano = ?
        """, (marca, modelo, ano))
        resultado = cursor.fetchone()
        conn.close()
        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar veículo: {e}")
        return None


def salvar_veiculo_cache(marca, modelo, ano, original, paralelo):
    try:
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO veiculos (marca, modelo, ano, original, paralelo, data_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            marca, modelo, ano, original, paralelo,
            datetime.now().strftime("%d/%m/%Y")
        ))
        conn.commit()
        conn.close()
        logger.info(f"Veículo salvo no cache: {marca} {modelo} {ano}")
    except Exception as e:
        logger.error(f"Erro ao salvar cache: {e}")


# ==================================================
# PESQUISA ONLINE — SERPAPI
# ==================================================

def extrair_preco_texto(texto):
    """Extrai preço de um texto. Aceita vários formatos brasileiros."""
    if not texto:
        return None

    padroes = [
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',  # R$ 1.800,00
        r'R\$\s*(\d{1,3}(?:\.\d{3})*)',          # R$ 1.800
        r'R\$\s*(\d+(?:,\d{2})?)',               # R$ 1800 ou R$ 1800,00
        r'R\$(\d+)',                              # R$1800
        r'(\d{1,3}(?:\.\d{3})+,\d{2})',          # 1.800,00 sem R$
    ]

    for padrao in padroes:
        match = re.search(padrao, texto)
        if match:
            valor_str = match.group(1).replace('.', '').replace(',', '.')
            try:
                valor = float(valor_str)
                if 200 <= valor <= 25000:
                    return valor
            except ValueError:
                continue

    return None


def extrair_precos_de_resultado(resultado_serp):
    """
    Extrai preços de um resultado SerpAPI.
    Prioridade: extracted_price (campo numérico) > price (string) > snippet (texto livre)
    """
    precos = []

    # 1. Shopping results — campo mais confiável
    for item in resultado_serp.get('shopping_results', [])[:8]:

        # extracted_price já é um float — uso direto
        extracted = item.get('extracted_price')
        if extracted:
            try:
                valor = float(extracted)
                if 200 <= valor <= 25000:
                    precos.append(valor)
                    logger.info(f"Preço extraído (shopping extracted_price): R$ {valor}")
                    continue
            except (ValueError, TypeError):
                pass

        # Fallback: campo price como string
        preco = extrair_preco_texto(str(item.get('price', '')))
        if preco:
            precos.append(preco)
            logger.info(f"Preço extraído (shopping price string): R$ {preco}")

    # 2. Inline shopping
    for item in resultado_serp.get('inline_shopping_results', [])[:5]:
        extracted = item.get('extracted_price')
        if extracted:
            try:
                valor = float(extracted)
                if 200 <= valor <= 25000:
                    precos.append(valor)
                    continue
            except (ValueError, TypeError):
                pass
        preco = extrair_preco_texto(str(item.get('price', '')))
        if preco:
            precos.append(preco)

    # 3. Resultados orgânicos — extrai do título + snippet
    if not precos:
        for item in resultado_serp.get('organic_results', [])[:5]:
            texto = f"{item.get('title', '')} {item.get('snippet', '')}"
            preco = extrair_preco_texto(texto)
            if preco:
                precos.append(preco)
                logger.info(f"Preço extraído (orgânico): R$ {preco}")

    return precos


def buscar_precos_online(marca, modelo, ano):
    """
    Busca preços via SerpAPI. Retorna (original, paralelo) ou (None, None).
    """
    try:
        from serp_service import pesquisar_google

        logger.info(f"Buscando preços online: {marca} {modelo} {ano}")

        resultado_original = pesquisar_google(
            f"parabrisa {marca} {modelo} {ano} original preço"
        )
        precos_original = extrair_precos_de_resultado(resultado_original)

        resultado_paralelo = pesquisar_google(
            f"parabrisa {marca} {modelo} {ano} paralelo preço"
        )
        precos_paralelo = extrair_precos_de_resultado(resultado_paralelo)

        logger.info(f"Preços originais encontrados: {precos_original}")
        logger.info(f"Preços paralelos encontrados: {precos_paralelo}")

        original = round(sum(precos_original) / len(precos_original), 2) if precos_original else None
        paralelo = round(sum(precos_paralelo) / len(precos_paralelo), 2) if precos_paralelo else None

        # Estima o que faltou com base no outro
        if original and not paralelo:
            paralelo = round(original * 0.65, 2)
            logger.info(f"Paralelo estimado: R$ {paralelo}")

        if paralelo and not original:
            original = round(paralelo / 0.65, 2)
            logger.info(f"Original estimado: R$ {original}")

        return original, paralelo

    except Exception as e:
        logger.error(f"Erro ao buscar preços online: {e}")
        return None, None


# ==================================================
# REGRAS DE NEGÓCIO
# ==================================================

def calcular_categoria(media):

    if media <= 1500:
        return {"categoria": "Popular",       "percentual": 35, "classe": "popular",       "icone": "🟢"}
    elif media <= 4000:
        return {"categoria": "Intermediário", "percentual": 20, "classe": "intermediario", "icone": "🟡"}

    return     {"categoria": "Premium",       "percentual": 10, "classe": "premium",       "icone": "🔴"}


def obter_teto(avarias):
    tetos = {1: 600, 2: 850, 3: 1100}
    return tetos.get(avarias, 1400)


# ==================================================
# PÁGINA PRINCIPAL
# ==================================================

@app.route("/", methods=["GET", "POST"])
def index():

    resultado = None
    mensagem  = None

    if request.method == "POST":

        marca   = request.form.get("marca",   "").strip()
        modelo  = request.form.get("modelo",  "").strip()
        ano     = request.form.get("ano",     "").strip()
        avarias = int(request.form.get("avarias", 1))

        if not marca or not modelo or not ano:
            mensagem = "Por favor, preencha todos os campos."
            return render_template("index.html", resultado=resultado, mensagem=mensagem)

        # 1. Banco local
        veiculo = buscar_veiculo(marca, modelo, ano)
        fonte   = "banco de dados"

        # 2. SerpAPI — se não achou no banco
        if not veiculo:
            logger.info("Veículo não encontrado no banco. Buscando online...")
            original_online, paralelo_online = buscar_precos_online(marca, modelo, ano)

            if original_online and paralelo_online:
                salvar_veiculo_cache(marca, modelo, ano, original_online, paralelo_online)
                veiculo = buscar_veiculo(marca, modelo, ano)
                fonte   = "pesquisa online"
            else:
                mensagem = (
                    f"Veículo não encontrado: {marca} {modelo} {ano}. "
                    f"Não foi possível localizar preços. "
                    f"Verifique se o nome está correto."
                )

        # 3. Calcula
        if veiculo:

            original         = float(veiculo[0])
            paralelo         = float(veiculo[1])
            data_atualizacao = veiculo[2]

            media = (original + paralelo) / 2

            info             = calcular_categoria(media)
            categoria        = info["categoria"]
            percentual_base  = info["percentual"]
            classe_categoria = info["classe"]
            icone_categoria  = info["icone"]

            percentual_final = percentual_base + ((avarias - 1) * 10)
            valor_calculado  = media * (percentual_final / 100)
            teto             = obter_teto(avarias)
            valor_final      = min(valor_calculado, teto)

            try:
                conn = sqlite3.connect(DB)
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO consultas (
                    marca, modelo, ano, original, paralelo, media,
                    categoria, percentual, avarias, valor_final, data_consulta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    marca, modelo, ano, original, paralelo, media,
                    categoria, percentual_final, avarias, valor_final,
                    datetime.now().strftime("%d/%m/%Y %H:%M")
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Erro ao salvar consulta: {e}")

            resultado = {
                "original":         original,
                "paralelo":         paralelo,
                "media":            media,
                "categoria":        categoria,
                "classe_categoria": classe_categoria,
                "icone_categoria":  icone_categoria,
                "percentual":       percentual_final,
                "teto":             teto,
                "valor_final":      valor_final,
                "data_atualizacao": data_atualizacao,
                "fonte":            fonte,
            }

    return render_template("index.html", resultado=resultado, mensagem=mensagem)


# ==================================================
# HISTÓRICO — com paginação
# ==================================================

@app.route("/historico")
def historico():

    try:
        pagina     = int(request.args.get("pagina", 1))
        por_pagina = 10

        conn   = sqlite3.connect(DB)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM consultas")
        total_registros = cursor.fetchone()[0]

        total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
        pagina        = max(1, min(pagina, total_paginas))
        offset        = (pagina - 1) * por_pagina

        cursor.execute("""
        SELECT data_consulta, marca, modelo, ano, media, valor_final
        FROM consultas
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """, (por_pagina, offset))

        dados = cursor.fetchall()
        conn.close()

    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {e}")
        dados           = []
        pagina          = 1
        total_paginas   = 1
        total_registros = 0

    return render_template(
        "historico.html",
        dados=dados,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros
    )


# ==================================================
# INICIALIZAÇÃO LOCAL
# ==================================================

if __name__ == "__main__":

    debug_mode = os.getenv("FLASK_DEBUG", "False") == "True"

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=debug_mode
    )
