from flask import Flask, render_template, request, send_file
from flask_wtf.csrf import CSRFProtect
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

# ==================================================
# BANCO DE DADOS — PostgreSQL (Render) ou SQLite (local)
# ==================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    PH  = "%s"       # placeholder PostgreSQL
    logger.info("Usando PostgreSQL")
else:
    import sqlite3
    PH  = "?"        # placeholder SQLite
    DB  = "database.db"
    logger.info("Usando SQLite local")


def get_conn():
    """Retorna conexão com o banco correto."""
    if DATABASE_URL:
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        return sqlite3.connect(DB)


def criar_banco():

    conn   = get_conn()
    cursor = conn.cursor()

    if DATABASE_URL:
        # PostgreSQL
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id SERIAL PRIMARY KEY,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, data_atualizacao TEXT
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id SERIAL PRIMARY KEY,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, media REAL,
            categoria TEXT, percentual REAL, avarias INTEGER,
            valor_final REAL, data_consulta TEXT
        )
        """)
    else:
        # SQLite
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, data_atualizacao TEXT
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, media REAL,
            categoria TEXT, percentual REAL, avarias INTEGER,
            valor_final REAL, data_consulta TEXT
        )
        """)

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM veiculos")
    total = cursor.fetchone()[0]

    if total == 0:
        hoje = datetime.now().strftime("%d/%m/%Y")
        veiculos_teste = [
            ("Chevrolet", "Onix",   "2022", 1700, 1100, hoje),
            ("Fiat",      "Argo",   "2022", 1800, 1200, hoje),
            ("Hyundai",   "HB20",   "2023", 1900, 1300, hoje),
            ("BMW",       "X3",     "2022", 7000, 2800, hoje),
            ("Volkswagen","Polo",   "2023", 2200, 1450, hoje),
            ("Toyota",    "Corolla","2023", 3500, 2100, hoje),
        ]
        for v in veiculos_teste:
            cursor.execute(
                f"INSERT INTO veiculos (marca,modelo,ano,original,paralelo,data_atualizacao) VALUES ({PH},{PH},{PH},{PH},{PH},{PH})",
                v
            )
        conn.commit()
        logger.info("Banco criado com dados iniciais.")

    conn.close()


# ==================================================
# ✅ INICIALIZA — roda com Gunicorn também
# ==================================================

criar_banco()


# ==================================================
# BUSCA NO BANCO LOCAL
# ==================================================

def buscar_veiculo(marca, modelo, ano):
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT original, paralelo, data_atualizacao FROM veiculos WHERE LOWER(marca)=LOWER({PH}) AND LOWER(modelo)=LOWER({PH}) AND ano={PH}",
            (marca, modelo, ano)
        )
        resultado = cursor.fetchone()
        conn.close()
        return resultado
    except Exception as e:
        logger.error(f"Erro ao buscar veículo: {e}")
        return None


def salvar_veiculo_cache(marca, modelo, ano, original, paralelo):
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO veiculos (marca,modelo,ano,original,paralelo,data_atualizacao) VALUES ({PH},{PH},{PH},{PH},{PH},{PH})",
            (marca, modelo, ano, original, paralelo, datetime.now().strftime("%d/%m/%Y"))
        )
        conn.commit()
        conn.close()
        logger.info(f"Veículo salvo no cache: {marca} {modelo} {ano}")
    except Exception as e:
        logger.error(f"Erro ao salvar cache: {e}")


# ==================================================
# SERPAPI — PESQUISA ONLINE
# ==================================================

def extrair_preco_texto(texto):
    if not texto:
        return None
    padroes = [
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
        r'R\$\s*(\d{1,3}(?:\.\d{3})*)',
        r'R\$\s*(\d+(?:,\d{2})?)',
        r'R\$(\d+)',
        r'(\d{1,3}(?:\.\d{3})+,\d{2})',
    ]
    for padrao in padroes:
        match = re.search(padrao, texto)
        if match:
            try:
                valor = float(match.group(1).replace('.', '').replace(',', '.'))
                if 200 <= valor <= 25000:
                    return valor
            except ValueError:
                continue
    return None


def extrair_precos_de_resultado(resultado_serp):
    precos = []

    for item in resultado_serp.get('shopping_results', [])[:8]:
        extracted = item.get('extracted_price')
        if extracted is not None:
            try:
                v = float(extracted)
                if 200 <= v <= 25000:
                    precos.append(v)
                    continue
            except (ValueError, TypeError):
                pass
        p = extrair_preco_texto(str(item.get('price', '')))
        if p:
            precos.append(p)

    for item in resultado_serp.get('inline_shopping_results', [])[:5]:
        extracted = item.get('extracted_price')
        if extracted is not None:
            try:
                v = float(extracted)
                if 200 <= v <= 25000:
                    precos.append(v)
                    continue
            except (ValueError, TypeError):
                pass
        p = extrair_preco_texto(str(item.get('price', '')))
        if p:
            precos.append(p)

    if not precos:
        for item in resultado_serp.get('organic_results', [])[:8]:
            texto = f"{item.get('title', '')} {item.get('snippet', '')}"
            p = extrair_preco_texto(texto)
            if p:
                precos.append(p)

    return precos


def buscar_precos_online(marca, modelo, ano):
    try:
        from serp_service import pesquisar_google
        logger.info(f"Buscando online: {marca} {modelo} {ano}")

        r_orig = pesquisar_google(f"parabrisa {marca} {modelo} {ano} original preço")
        precos_orig = extrair_precos_de_resultado(r_orig)

        r_par = pesquisar_google(f"parabrisa {marca} {modelo} {ano} paralelo preço")
        precos_par = extrair_precos_de_resultado(r_par)

        logger.info(f"Preços originais: {precos_orig}")
        logger.info(f"Preços paralelos: {precos_par}")

        original = round(sum(precos_orig) / len(precos_orig), 2) if precos_orig else None
        paralelo = round(sum(precos_par)  / len(precos_par),  2) if precos_par  else None

        if original and not paralelo:
            paralelo = round(original * 0.65, 2)
        if paralelo and not original:
            original = round(paralelo / 0.65, 2)

        if original and paralelo and paralelo > original:
            original, paralelo = paralelo, original
            logger.info("Preços invertidos (paralelo era maior)")

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
    return {1: 600, 2: 850, 3: 1100}.get(avarias, 1400)


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

        veiculo = buscar_veiculo(marca, modelo, ano)
        fonte   = "banco de dados"

        if not veiculo:
            original_online, paralelo_online = buscar_precos_online(marca, modelo, ano)
            if original_online and paralelo_online:
                salvar_veiculo_cache(marca, modelo, ano, original_online, paralelo_online)
                veiculo = buscar_veiculo(marca, modelo, ano)
                fonte   = "pesquisa online"
            else:
                mensagem = f"Veículo não encontrado: {marca} {modelo} {ano}. Verifique se o nome está correto."

        if veiculo:
            original         = float(veiculo[0])
            paralelo         = float(veiculo[1])
            data_atualizacao = veiculo[2]
            media            = (original + paralelo) / 2

            info             = calcular_categoria(media)
            percentual_final = info["percentual"] + ((avarias - 1) * 10)
            valor_calculado  = media * (percentual_final / 100)
            teto             = obter_teto(avarias)
            valor_final      = min(valor_calculado, teto)

            try:
                conn   = get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    f"""INSERT INTO consultas (marca,modelo,ano,original,paralelo,media,categoria,percentual,avarias,valor_final,data_consulta)
                        VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})""",
                    (marca, modelo, ano, original, paralelo, media,
                     info["categoria"], percentual_final, avarias, valor_final,
                     datetime.now().strftime("%d/%m/%Y %H:%M"))
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Erro ao salvar consulta: {e}")

            resultado = {
                "original": original, "paralelo": paralelo, "media": media,
                "categoria": info["categoria"], "classe_categoria": info["classe"],
                "icone_categoria": info["icone"],
                "percentual": percentual_final, "teto": teto,
                "valor_final": valor_final, "data_atualizacao": data_atualizacao,
                "fonte": fonte, "avarias": avarias,
            }

    return render_template("index.html", resultado=resultado, mensagem=mensagem)


# ==================================================
# HISTÓRICO
# ==================================================

@app.route("/historico")
def historico():
    try:
        pagina     = int(request.args.get("pagina", 1))
        por_pagina = 10

        conn   = get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM consultas")
        total_registros = cursor.fetchone()[0]

        total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
        pagina        = max(1, min(pagina, total_paginas))
        offset        = (pagina - 1) * por_pagina

        # item[0]=id, [1]=data, [2]=marca, [3]=modelo, [4]=ano,
        # [5]=original, [6]=paralelo, [7]=media, [8]=avarias, [9]=valor_final
        cursor.execute(
            f"""SELECT id, data_consulta, marca, modelo, ano,
                       original, paralelo, media, avarias, valor_final
                FROM consultas ORDER BY id DESC LIMIT {PH} OFFSET {PH}""",
            (por_pagina, offset)
        )
        dados = cursor.fetchall()
        conn.close()

    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {e}")
        dados = []; pagina = 1; total_paginas = 1; total_registros = 0

    return render_template(
        "historico.html",
        dados=dados, pagina=pagina,
        total_paginas=total_paginas, total_registros=total_registros
    )


# ==================================================
# EXPORTAR PDF
# ==================================================

@app.route("/exportar-pdf")
def exportar_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from io import BytesIO

        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT data_consulta, marca, modelo, ano, original, paralelo, media, avarias, valor_final
        FROM consultas ORDER BY id DESC LIMIT 100
        """)
        dados = cursor.fetchall()
        conn.close()

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=40, leftMargin=40,
                                topMargin=50, bottomMargin=40)

        estilos   = getSampleStyleSheet()
        elementos = []

        titulo_estilo = ParagraphStyle("t", parent=estilos["Title"],
                                       fontSize=18, spaceAfter=6,
                                       textColor=colors.HexColor("#0d6efd"))
        elementos.append(Paragraph("Histórico de Consultas", titulo_estilo))

        sub_estilo = ParagraphStyle("s", parent=estilos["Normal"],
                                    fontSize=10, spaceAfter=20, textColor=colors.grey)
        elementos.append(Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — {len(dados)} registros",
            sub_estilo
        ))

        cabecalho = ["Data", "Veículo", "Original", "Paralelo", "Média", "Avarias", "Valor de Serviço"]
        linhas    = [cabecalho]

        for row in dados:
            av  = row[7]
            txt = f"{av} avaria" if av == 1 else f"{av} avarias"
            linhas.append([
                str(row[0]),
                f"{row[1]} {row[2]} {row[3]}",
                f"R$ {row[4]:.2f}",
                f"R$ {row[5]:.2f}",
                f"R$ {row[6]:.2f}",
                txt,
                f"R$ {row[8]:.2f}"
            ])

        tabela = Table(linhas, repeatRows=1)
        tabela.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#0d6efd")),
            ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,0),  10),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#f0f8ff")]),
            ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",      (0,1), (-1,-1), 9),
            ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ]))

        elementos.append(tabela)
        doc.build(elementos)
        buffer.seek(0)

        return send_file(
            buffer, mimetype="application/pdf", as_attachment=True,
            download_name=f"historico_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        )

    except Exception as e:
        logger.error(f"Erro ao gerar PDF: {e}")
        return f"Erro ao gerar PDF: {e}", 500


# ==================================================
# INICIALIZAÇÃO LOCAL
# ==================================================

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "False") == "True"
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=debug_mode)
