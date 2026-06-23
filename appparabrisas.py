from flask import Flask, render_template, request, send_file
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
        r'R\$\s*(\d+(?:,\d{2})?)',               # R$ 1800
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
    Extrai preços de um resultado SerpAPI com logs detalhados para diagnóstico.
    """
    precos = []

    shopping = resultado_serp.get('shopping_results', [])
    inline   = resultado_serp.get('inline_shopping_results', [])
    organic  = resultado_serp.get('organic_results', [])

    logger.info(f"  Shopping results: {len(shopping)} itens")
    logger.info(f"  Inline shopping:  {len(inline)} itens")
    logger.info(f"  Organic results:  {len(organic)} itens")

    # Log do primeiro item de cada tipo para diagnóstico
    if shopping:
        primeiro = shopping[0]
        logger.info(f"  Primeiro shopping → price='{primeiro.get('price')}' extracted_price='{primeiro.get('extracted_price')}'")

    if organic:
        logger.info(f"  Primeiro organic snippet: {organic[0].get('snippet', '')[:150]}")

    # 1. Shopping results — tenta extracted_price (float direto) ou price (string)
    for item in shopping[:8]:
        extracted = item.get('extracted_price')
        if extracted is not None:
            try:
                valor = float(extracted)
                if 200 <= valor <= 25000:
                    precos.append(valor)
                    logger.info(f"  ✅ extracted_price: R$ {valor}")
                    continue
            except (ValueError, TypeError):
                pass

        preco = extrair_preco_texto(str(item.get('price', '')))
        if preco:
            precos.append(preco)
            logger.info(f"  ✅ price string: R$ {preco}")

    # 2. Inline shopping
    for item in inline[:5]:
        extracted = item.get('extracted_price')
        if extracted is not None:
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
        for item in organic[:8]:
            texto = f"{item.get('title', '')} {item.get('snippet', '')}"
            preco = extrair_preco_texto(texto)
            if preco:
                precos.append(preco)
                logger.info(f"  ✅ orgânico: R$ {preco}")

    return precos


def buscar_precos_online(marca, modelo, ano):
    """Busca preços via SerpAPI. Retorna (original, paralelo) ou (None, None)."""
    try:
        from serp_service import pesquisar_google

        logger.info(f"Buscando online: {marca} {modelo} {ano}")

        # Busca original
        logger.info("--- Busca ORIGINAL ---")
        resultado_original = pesquisar_google(
            f"parabrisa {marca} {modelo} {ano} original preço"
        )
        precos_original = extrair_precos_de_resultado(resultado_original)

        # Busca paralelo
        logger.info("--- Busca PARALELO ---")
        resultado_paralelo = pesquisar_google(
            f"parabrisa {marca} {modelo} {ano} paralelo preço"
        )
        precos_paralelo = extrair_precos_de_resultado(resultado_paralelo)

        logger.info(f"Preços originais: {precos_original}")
        logger.info(f"Preços paralelos: {precos_paralelo}")

        original = round(sum(precos_original) / len(precos_original), 2) if precos_original else None
        paralelo = round(sum(precos_paralelo) / len(precos_paralelo), 2) if precos_paralelo else None

        if original and not paralelo:
            paralelo = round(original * 0.65, 2)
            logger.info(f"Paralelo estimado: R$ {paralelo}")

        if paralelo and not original:
            original = round(paralelo / 0.65, 2)
            logger.info(f"Original estimado: R$ {original}")

        # ✅ Garantir que original sempre é maior que paralelo
        if original and paralelo and paralelo > original:
            logger.info(f"Invertendo preços (paralelo > original): {original} <-> {paralelo}")
            original, paralelo = paralelo, original

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
# ✅ HISTÓRICO — query retorna TODAS as colunas
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

        # id[0], data[1], marca[2], modelo[3], ano[4], original[5], paralelo[6], media[7], avarias[8], valor_final[9]
        cursor.execute("""
        SELECT id, data_consulta, marca, modelo, ano,
               original, paralelo, media, avarias, valor_final
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
# EXPORTAR PDF
# ==================================================

@app.route("/exportar-pdf")
def exportar_pdf():

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from io import BytesIO

        conn   = sqlite3.connect(DB)
        cursor = conn.cursor()
        cursor.execute("""
        SELECT data_consulta, marca, modelo, ano,
               original, paralelo, media, avarias, valor_final
        FROM consultas
        ORDER BY id DESC
        LIMIT 100
        """)
        dados = cursor.fetchall()
        conn.close()

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=50,
            bottomMargin=40
        )

        estilos = getSampleStyleSheet()
        elementos = []

        # Título
        titulo_estilo = ParagraphStyle(
            "titulo",
            parent=estilos["Title"],
            fontSize=18,
            spaceAfter=6,
            textColor=colors.HexColor("#0d6efd")
        )
        elementos.append(Paragraph("Histórico de Consultas", titulo_estilo))

        sub_estilo = ParagraphStyle(
            "sub",
            parent=estilos["Normal"],
            fontSize=10,
            spaceAfter=20,
            textColor=colors.grey
        )
        from datetime import datetime as dt
        elementos.append(Paragraph(
            f"Gerado em {dt.now().strftime('%d/%m/%Y %H:%M')} — {len(dados)} registros",
            sub_estilo
        ))

        # Tabela
        cabecalho = ["Data", "Veículo", "Original", "Paralelo", "Média", "Avarias", "Valor de Serviço"]
        linhas = [cabecalho]

        for row in dados:
            avarias = int(row[7])
            linhas.append([
                str(row[0]),
                f"{row[1]} {row[2]} {row[3]}",
                f"R$ {row[4]:.2f}",
                f"R$ {row[5]:.2f}",
                f"R$ {row[6]:.2f}",
                f"{avarias} avaria{'s' if avarias > 1 else ''}",
                f"R$ {row[8]:.2f}"
            ])

        tabela = Table(linhas, repeatRows=1)
        tabela.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#0d6efd")),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  11),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f8ff")]),
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (-1, -1), 10),
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]))

        elementos.append(tabela)
        doc.build(elementos)

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"historico_parabrisas_{dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        )

    except Exception as e:
        logger.error(f"Erro ao gerar PDF: {e}")
        return f"Erro ao gerar PDF: {e}", 500


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
