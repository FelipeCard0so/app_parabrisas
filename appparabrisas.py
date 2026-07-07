from flask import Flask, render_template, request, send_file, jsonify
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
    import pg8000
    from urllib.parse import urlparse as _urlparse
    PH = "%s"
    logger.info("Usando PostgreSQL")
else:
    import sqlite3
    PH = "?"
    DB = "database.db"
    logger.info("Usando SQLite local")


def get_conn():
    """Retorna conexão com o banco correto."""
    if DATABASE_URL:
        import ssl
        url = _urlparse(DATABASE_URL)
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return pg8000.connect(
            host=url.hostname,
            database=url.path.lstrip("/"),
            user=url.username,
            password=url.password,
            port=url.port or 5432,
            ssl_context=ssl_ctx
        )
    else:
        return sqlite3.connect(DB)


# ==================================================
# BANCO — CRIAÇÃO DAS TABELAS
# ==================================================

def criar_banco():
    conn   = get_conn()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id SERIAL PRIMARY KEY,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, data_atualizacao TEXT
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id SERIAL PRIMARY KEY,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, media REAL,
            categoria TEXT, percentual REAL, avarias INTEGER,
            valor_final REAL, data_consulta TEXT
        )""")
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, data_atualizacao TEXT
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT, modelo TEXT, ano TEXT,
            original REAL, paralelo REAL, media REAL,
            categoria TEXT, percentual REAL, avarias INTEGER,
            valor_final REAL, data_consulta TEXT
        )""")

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM veiculos")
    if cursor.fetchone()[0] == 0:
        hoje = datetime.now().strftime("%d/%m/%Y")
        for v in [
            ("Chevrolet", "Onix",    "2022", 1700, 1100, hoje),
            ("Fiat",      "Argo",    "2022", 1800, 1200, hoje),
            ("Hyundai",   "HB20",    "2023", 1900, 1300, hoje),
            ("BMW",       "X3",      "2022", 7000, 2800, hoje),
            ("Volkswagen","Polo",    "2023", 2200, 1450, hoje),
            ("Toyota",    "Corolla", "2023", 3500, 2100, hoje),
        ]:
            cursor.execute(
                f"INSERT INTO veiculos (marca,modelo,ano,original,paralelo,data_atualizacao) VALUES ({PH},{PH},{PH},{PH},{PH},{PH})", v
            )
        conn.commit()
        logger.info("Banco criado com dados iniciais.")

    conn.close()


# ✅ Executa na importação — funciona com Gunicorn
criar_banco()


# ==================================================
# HELPERS — BANCO
# ==================================================

def buscar_veiculo(marca, modelo, ano):
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT original,paralelo,data_atualizacao FROM veiculos WHERE LOWER(marca)=LOWER({PH}) AND LOWER(modelo)=LOWER({PH}) AND ano={PH}",
            (marca, modelo, ano)
        )
        r = cursor.fetchone()
        conn.close()
        return r
    except Exception as e:
        logger.error(f"Erro buscar_veiculo: {e}")
        return None


def salvar_veiculo_cache(marca, modelo, ano, original, paralelo):
    """
    INSERT se novo, UPDATE preservando data se já existe.
    """
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id FROM veiculos WHERE LOWER(marca)=LOWER({PH}) AND LOWER(modelo)=LOWER({PH}) AND ano={PH}",
            (marca, modelo, ano)
        )
        existe = cursor.fetchone()
        if existe:
            cursor.execute(
                f"UPDATE veiculos SET original={PH}, paralelo={PH} WHERE id={PH}",
                (original, paralelo, existe[0])
            )
            logger.info(f"Cache atualizado (data preservada): {marca} {modelo} {ano}")
        else:
            cursor.execute(
                f"INSERT INTO veiculos (marca,modelo,ano,original,paralelo,data_atualizacao) VALUES ({PH},{PH},{PH},{PH},{PH},{PH})",
                (marca, modelo, ano, original, paralelo, datetime.now().strftime("%d/%m/%Y"))
            )
            logger.info(f"Novo veículo no cache: {marca} {modelo} {ano}")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Erro salvar_veiculo_cache: {e}")


# ==================================================
# SERPAPI — EXTRAÇÃO DE PREÇOS
# ==================================================

def extrair_preco_texto(texto):
    """Extrai o primeiro preço entre R$400 e R$25.000 de um texto."""
    if not texto:
        return None
    padroes = [
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
        r'R\$\s*(\d{1,3}(?:\.\d{3})*)',
        r'R\$\s*(\d+(?:,\d{2})?)',
        r'R\$(\d+)',
        r'(\d{1,3}(?:\.\d{3})+,\d{2})',
    ]
    for p in padroes:
        m = re.search(p, texto)
        if m:
            try:
                v = float(m.group(1).replace('.', '').replace(',', '.'))
                if 400 <= v <= 25000:
                    return v
            except ValueError:
                continue
    return None


def extrair_precos_de_resultado(resultado_serp):
    """
    Extrai preços de um resultado SerpAPI.
    Prioridade: shopping (extracted_price) > shopping (price string) > organic (com filtro de contexto)
    """
    precos = []

    # 1. Shopping results
    for item in resultado_serp.get('shopping_results', [])[:8]:
        ext = item.get('extracted_price')
        if ext is not None:
            try:
                v = float(ext)
                if 400 <= v <= 25000:
                    precos.append(v)
                    continue
            except (ValueError, TypeError):
                pass
        p = extrair_preco_texto(str(item.get('price', '')))
        if p:
            precos.append(p)

    # 2. Inline shopping
    for item in resultado_serp.get('inline_shopping_results', [])[:5]:
        ext = item.get('extracted_price')
        if ext is not None:
            try:
                v = float(ext)
                if 400 <= v <= 25000:
                    precos.append(v)
                    continue
            except (ValueError, TypeError):
                pass
        p = extrair_preco_texto(str(item.get('price', '')))
        if p:
            precos.append(p)

    # 3. Organic results — só aceita se menciona para-brisa/vidro
    if not precos:
        for item in resultado_serp.get('organic_results', [])[:8]:
            texto = f"{item.get('title', '')} {item.get('snippet', '')}"
            if not any(t in texto.lower() for t in ['parabrisa', 'vidro', 'brisa']):
                continue
            p = extrair_preco_texto(texto)
            if p:
                precos.append(p)
                logger.info(f"  Orgânico aceito: R$ {p} | {texto[:80]}")

    return precos


def remover_outliers(precos):
    """Remove preços muito fora da mediana (25%–350%)."""
    if len(precos) < 3:
        return precos
    med = sorted(precos)[len(precos) // 2]
    return [p for p in precos if 0.25 * med <= p <= 3.5 * med]


def buscar_precos_online(marca, modelo, ano):
    """Busca preços via SerpAPI. Retorna (original, paralelo) ou (None, None)."""
    try:
        from serp_service import pesquisar_google
        logger.info(f"Buscando online: {marca} {modelo} {ano}")

        r_orig = pesquisar_google(f"parabrisa {marca} {modelo} {ano} original preço")
        p_orig = remover_outliers(extrair_precos_de_resultado(r_orig))

        r_par  = pesquisar_google(f"parabrisa {marca} {modelo} {ano} paralelo preço")
        p_par  = remover_outliers(extrair_precos_de_resultado(r_par))

        logger.info(f"Originais encontrados: {p_orig}")
        logger.info(f"Paralelos encontrados: {p_par}")

        original = round(sum(p_orig) / len(p_orig), 2) if p_orig else None
        paralelo = round(sum(p_par)  / len(p_par),  2) if p_par  else None

        if original and not paralelo:
            paralelo = round(original * 0.65, 2)
            logger.info(f"Paralelo estimado: R$ {paralelo}")
        if paralelo and not original:
            original = round(paralelo / 0.65, 2)
            logger.info(f"Original estimado: R$ {original}")
        if original and paralelo and paralelo > original:
            original, paralelo = paralelo, original
            logger.info("Preços invertidos (paralelo era maior)")

        return original, paralelo

    except Exception as e:
        logger.error(f"Erro buscar_precos_online: {e}")
        return None, None


# ==================================================
# STATUS SERPAPI
# ==================================================

def get_serpapi_status():
    """Retorna dados reais de uso da SerpAPI."""
    try:
        api_key = os.getenv("SERPAPI_KEY")
        if not api_key:
            return None
        from serpapi import GoogleSearch
        data   = GoogleSearch({"api_key": api_key}).get_account()
        restam = int(
            data.get("plan_searches_left") or
            data.get("total_searches_left") or
            data.get("searches_left") or 0
        )
        total  = int(
            data.get("plan_monthly_searches") or
            data.get("searches_per_month") or
            data.get("monthly_searches") or 250
        )
        return {"restam": restam, "total": total}
    except Exception as e:
        logger.error(f"Erro get_serpapi_status: {e}")
        return None


# ==================================================
# REGRAS DE NEGÓCIO
# ==================================================

def calcular_categoria(media):
    """
    Popular     (≤ R$1.500): 35%
    Intermediário (R$1.501–4.000): 20%
    Premium     (> R$4.000): 10%
    """
    if media <= 1500:
        return {"categoria": "Popular",       "percentual": 35, "classe": "popular",       "icone": "🟢"}
    elif media <= 4000:
        return {"categoria": "Intermediário", "percentual": 20, "classe": "intermediario", "icone": "🟡"}
    return     {"categoria": "Premium",       "percentual": 10, "classe": "premium",       "icone": "🔴"}


def obter_teto(avarias):
    """Valor máximo de reparo por quantidade de avarias."""
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

        # 1. Busca no banco local
        veiculo = buscar_veiculo(marca, modelo, ano)
        fonte   = "banco de dados"

        # 2. Se não achou, busca online via SerpAPI
        if not veiculo:
            orig_on, par_on = buscar_precos_online(marca, modelo, ano)
            if orig_on and par_on:
                salvar_veiculo_cache(marca, modelo, ano, orig_on, par_on)
                veiculo = buscar_veiculo(marca, modelo, ano)
                fonte   = "pesquisa online"
            else:
                mensagem = (
                    f"Veículo não encontrado: {marca} {modelo} {ano}. "
                    f"Verifique o nome ou tente novamente."
                )

        # 3. Calcula e salva
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
                    f"""INSERT INTO consultas
                        (marca,modelo,ano,original,paralelo,media,categoria,percentual,avarias,valor_final,data_consulta)
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
                "original":         original,
                "paralelo":         paralelo,
                "media":            media,
                "categoria":        info["categoria"],
                "classe_categoria": info["classe"],
                "icone_categoria":  info["icone"],
                "percentual":       percentual_final,
                "teto":             teto,
                "valor_final":      valor_final,
                "data_atualizacao": data_atualizacao,
                "fonte":            fonte,
                "avarias":          avarias,
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
        total_paginas   = max(1, (total_registros + por_pagina - 1) // por_pagina)
        pagina          = max(1, min(pagina, total_paginas))
        offset          = (pagina - 1) * por_pagina

        # Colunas: [0]=id [1]=data_consulta [2]=marca [3]=modelo [4]=ano
        #          [5]=original [6]=paralelo [7]=media [8]=avarias [9]=valor_final
        cursor.execute(
            f"""SELECT id, data_consulta, marca, modelo, ano,
                       original, paralelo, media, avarias, valor_final
                FROM consultas
                ORDER BY id DESC
                LIMIT {PH} OFFSET {PH}""",
            (por_pagina, offset)
        )
        dados = cursor.fetchall()
        conn.close()

    except Exception as e:
        logger.error(f"Erro histórico: {e}")
        dados = []; pagina = 1; total_paginas = 1; total_registros = 0

    serpapi_status = get_serpapi_status()

    return render_template(
        "historico.html",
        dados=dados,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        serpapi_status=serpapi_status
    )


# ==================================================
# EDITAR CONSULTA — isenta de CSRF (chamada via fetch)
# ==================================================

@app.route("/editar-consulta/<int:consulta_id>", methods=["POST"])
@csrf.exempt
def editar_consulta(consulta_id):
    try:
        original_novo = float(request.form.get("original", 0))
        paralelo_novo = float(request.form.get("paralelo", 0))

        if original_novo <= 0 or paralelo_novo <= 0:
            return jsonify({"erro": "Valores inválidos"}), 400

        # Garante original >= paralelo
        if paralelo_novo > original_novo:
            original_novo, paralelo_novo = paralelo_novo, original_novo

        conn   = get_conn()
        cursor = conn.cursor()

        cursor.execute(f"SELECT avarias FROM consultas WHERE id={PH}", (consulta_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({"erro": "Consulta não encontrada"}), 404

        avarias          = int(row[0])
        media            = (original_novo + paralelo_novo) / 2
        info             = calcular_categoria(media)
        percentual_final = info["percentual"] + ((avarias - 1) * 10)
        valor_final      = min(media * (percentual_final / 100), obter_teto(avarias))

        cursor.execute(
            f"""UPDATE consultas SET
                    original={PH}, paralelo={PH}, media={PH},
                    categoria={PH}, percentual={PH}, valor_final={PH}
                WHERE id={PH}""",
            (original_novo, paralelo_novo, media,
             info["categoria"], percentual_final, valor_final, consulta_id)
        )
        conn.commit()
        conn.close()

        return jsonify({
            "ok":          True,
            "original":    f"{original_novo:.2f}",
            "paralelo":    f"{paralelo_novo:.2f}",
            "media":       f"{media:.2f}",
            "valor_final": f"{valor_final:.2f}",
            "categoria":   info["categoria"],
            "classe":      info["classe"],
            "icone":       info["icone"],
        })

    except Exception as e:
        logger.error(f"Erro editar_consulta {consulta_id}: {e}")
        return jsonify({"erro": str(e)}), 500


# ==================================================
# EXCLUIR CONSULTA — isenta de CSRF (chamada via fetch)
# ==================================================

@app.route("/excluir-consulta/<int:consulta_id>", methods=["POST"])
@csrf.exempt
def excluir_consulta(consulta_id):
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM consultas WHERE id={PH}", (consulta_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Erro excluir_consulta {consulta_id}: {e}")
        return jsonify({"erro": str(e)}), 500


# ==================================================
# EXPORTAR PDF
# ==================================================

@app.route("/exportar-pdf")
def exportar_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from io import BytesIO

        filtro_marca  = request.args.get('marca',  '').strip()
        filtro_modelo = request.args.get('modelo', '').strip()

        conn   = get_conn()
        cursor = conn.cursor()
        query  = """SELECT data_consulta, marca, modelo, ano,
                           original, paralelo, media, avarias, valor_final
                    FROM consultas WHERE 1=1"""
        params = []
        if filtro_marca:
            query += f" AND LOWER(marca) LIKE LOWER({PH})"
            params.append(f'%{filtro_marca}%')
        if filtro_modelo:
            query += f" AND LOWER(modelo) LIKE LOWER({PH})"
            params.append(f'%{filtro_modelo}%')
        query += " ORDER BY id DESC LIMIT 100"
        cursor.execute(query, params)
        dados = cursor.fetchall()
        conn.close()

        # Título reflete filtro ativo
        titulo_filtro = ""
        if filtro_marca and filtro_modelo:
            titulo_filtro = f" — {filtro_marca} {filtro_modelo}"
        elif filtro_marca:
            titulo_filtro = f" — {filtro_marca}"
        elif filtro_modelo:
            titulo_filtro = f" — {filtro_modelo}"

        buffer = BytesIO()
        doc    = SimpleDocTemplate(buffer, pagesize=A4,
                                   rightMargin=40, leftMargin=40,
                                   topMargin=50,  bottomMargin=40)
        estilos   = getSampleStyleSheet()
        elementos = []

        elementos.append(Paragraph(
            f"Histórico de Consultas{titulo_filtro}",
            ParagraphStyle("t", parent=estilos["Title"], fontSize=18,
                           spaceAfter=6, textColor=colors.HexColor("#0d6efd"))
        ))

        rodape = f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — {len(dados)} registro(s)"
        if filtro_marca or filtro_modelo:
            rodape += f" | Filtro: {filtro_marca} {filtro_modelo}".strip()
        elementos.append(Paragraph(
            rodape,
            ParagraphStyle("s", parent=estilos["Normal"], fontSize=10,
                           spaceAfter=20, textColor=colors.grey)
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
            ("BACKGROUND",     (0,0), (-1,0),  colors.HexColor("#0d6efd")),
            ("TEXTCOLOR",      (0,0), (-1,0),  colors.white),
            ("FONTNAME",       (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0,0), (-1,0),  10),
            ("ALIGN",          (0,0), (-1,-1), "CENTER"),
            ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f8ff")]),
            ("FONTNAME",       (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",       (0,1), (-1,-1), 9),
            ("GRID",           (0,0), (-1,-1), 0.5, colors.HexColor("#dee2e6")),
            ("TOPPADDING",     (0,0), (-1,-1), 7),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 7),
        ]))

        elementos.append(tabela)
        doc.build(elementos)
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"historico_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        )

    except Exception as e:
        logger.error(f"Erro exportar_pdf: {e}")
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
