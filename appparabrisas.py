from flask import Flask, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
import sqlite3
import logging
from datetime import datetime
from functools import wraps
import os
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors

# ============================================================
# CONFIGURAÇÃO INICIAL
# ============================================================

app = Flask(__name__)

# ✅ Configuração de Segurança
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
app.config['DEBUG'] = os.getenv('FLASK_DEBUG', 'False') == 'True'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ✅ CSRF Protection
csrf = CSRFProtect(app)

# ✅ Rate Limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# ✅ Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB = "database.db"

# ============================================================
# ADICIONE ISSO NO INÍCIO DO appparabrisas.py
# (Logo após: DB = "database.db")
# ============================================================

# ✅ Inicializar banco automaticamente
def inicializar_banco_se_necessario():
    """Cria o banco na primeira execução"""
    try:
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()
        
        # Verificar se tabelas existem
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='consultas'")
        existe = cursor.fetchone()
        
        conn.close()
        
        if not existe:
            logger.info("Banco não existe, criando...")
            criar_banco()
        else:
            logger.info("Banco já existe")
    except Exception as e:
        logger.error(f"Erro ao verificar banco: {e}")
        criar_banco()


# ============================================================
# BANCO DE DADOS
# ============================================================

def criar_banco():
    """Cria tabelas no banco de dados"""
    try:
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()

        # Tabela de veículos (cache futuro)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            ano TEXT NOT NULL,
            original REAL NOT NULL,
            paralelo REAL NOT NULL,
            data_atualizacao TEXT NOT NULL,
            UNIQUE(marca, modelo, ano)
        )
        """)

        # Tabela de consultas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            ano TEXT NOT NULL,
            original REAL NOT NULL,
            paralelo REAL NOT NULL,
            media REAL NOT NULL,
            categoria TEXT NOT NULL,
            percentual REAL NOT NULL,
            avarias INTEGER NOT NULL,
            valor_final REAL NOT NULL,
            data_consulta TEXT NOT NULL
        )
        """)

        conn.commit()

        # ✅ Dados iniciais apenas se vazio
        cursor.execute("SELECT COUNT(*) FROM veiculos")
        total = cursor.fetchone()[0]

        if total == 0:
            veiculos_teste = [
                ("Chevrolet", "Onix", "2022", 1700, 1100, datetime.now().strftime("%d/%m/%Y")),
                ("Fiat", "Argo", "2022", 1800, 1200, datetime.now().strftime("%d/%m/%Y")),
                ("Hyundai", "HB20", "2023", 1900, 1300, datetime.now().strftime("%d/%m/%Y")),
                ("BMW", "X3", "2022", 7000, 2800, datetime.now().strftime("%d/%m/%Y"))
            ]

            cursor.executemany("""
            INSERT INTO veiculos (marca, modelo, ano, original, paralelo, data_atualizacao)
            VALUES (?, ?, ?, ?, ?, ?)
            """, veiculos_teste)

            conn.commit()

        logger.info("Banco de dados inicializado com sucesso")
        conn.close()

    except sqlite3.Error as e:
        logger.error(f"Erro ao criar banco de dados: {e}")
        raise


# ============================================================
# VALIDAÇÃO DE ENTRADA
# ============================================================

class ValidadorVeiculo:
    """Valida dados de entrada do veículo"""

    @staticmethod
    def validar_marca(marca):
        """Valida marca do veículo"""
        if not marca or not isinstance(marca, str):
            return False, "Marca inválida"

        marca = marca.strip()
        if len(marca) < 2 or len(marca) > 50:
            return False, "Marca deve ter entre 2 e 50 caracteres"

        if not all(c.isalnum() or c.isspace() or c in '-' for c in marca):
            return False, "Marca contém caracteres inválidos"

        return True, marca

    @staticmethod
    def validar_modelo(modelo):
        """Valida modelo do veículo"""
        if not modelo or not isinstance(modelo, str):
            return False, "Modelo inválido"

        modelo = modelo.strip()
        if len(modelo) < 2 or len(modelo) > 50:
            return False, "Modelo deve ter entre 2 e 50 caracteres"

        if not all(c.isalnum() or c.isspace() or c in '-.' for c in modelo):
            return False, "Modelo contém caracteres inválidos"

        return True, modelo

    @staticmethod
    def validar_ano(ano):
        """Valida ano do veículo"""
        try:
            ano_int = int(ano)
            ano_atual = datetime.now().year

            if ano_int < 1990 or ano_int > ano_atual + 1:
                return False, f"Ano deve estar entre 1990 e {ano_atual + 1}"

            return True, str(ano_int)
        except ValueError:
            return False, "Ano deve ser um número válido"

    @staticmethod
    def validar_avarias(avarias):
        """Valida quantidade de avarias"""
        try:
            avarias_int = int(avarias)

            if avarias_int < 1 or avarias_int > 10:
                return False, "Quantidade de avarias deve estar entre 1 e 10"

            return True, avarias_int
        except (ValueError, TypeError):
            return False, "Quantidade de avarias inválida"


# ============================================================
# FUNÇÕES DE BUSCA
# ============================================================

def buscar_veiculo(marca, modelo, ano):
    """Busca veículo no banco de dados com tratamento de erro"""
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

    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar veículo: {e}")
        return None


# ============================================================
# REGRAS DE NEGÓCIO
# ============================================================

def calcular_categoria(media):
    """
    Calcula categoria baseada no valor médio

    Popular: até R$ 1.500 (35%)
    Intermediário: R$ 1.501 a R$ 4.000 (20%)
    Premium: acima de R$ 4.000 (10%)
    """
    if media <= 1500:
        return {
            "categoria": "Popular",
            "percentual": 35,
            "classe": "popular",
            "icone": "🟢"
        }
    elif media <= 4000:
        return {
            "categoria": "Intermediário",
            "percentual": 20,
            "classe": "intermediario",
            "icone": "🟡"
        }
    return {
        "categoria": "Premium",
        "percentual": 10,
        "classe": "premium",
        "icone": "🔴"
    }


def obter_teto(avarias):
    """Retorna teto de valor baseado em avarias"""
    tetos = {1: 600, 2: 850, 3: 1100}
    return tetos.get(avarias, 1400)


# ============================================================
# ROTAS - PÁGINA PRINCIPAL
# ============================================================

@app.route("/", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def index():
    """Rota principal com formulário de consulta"""
    resultado = None
    mensagem = None
    tipo_erro = None

    if request.method == "POST":
        try:
            # ✅ Validar entrada
            valido, marca = ValidadorVeiculo.validar_marca(request.form.get("marca", ""))
            if not valido:
                mensagem = marca
                tipo_erro = "erro"
            else:
                valido, modelo = ValidadorVeiculo.validar_modelo(request.form.get("modelo", ""))
                if not valido:
                    mensagem = modelo
                    tipo_erro = "erro"
                else:
                    valido, ano = ValidadorVeiculo.validar_ano(request.form.get("ano", ""))
                    if not valido:
                        mensagem = ano
                        tipo_erro = "erro"
                    else:
                        valido, avarias = ValidadorVeiculo.validar_avarias(request.form.get("avarias", ""))
                        if not valido:
                            mensagem = avarias
                            tipo_erro = "erro"
                        else:
                            # ✅ Buscar veículo
                            veiculo = buscar_veiculo(marca, modelo, ano)

                            if veiculo:
                                # ✅ Calcular resultado
                                original = float(veiculo[0])
                                paralelo = float(veiculo[1])
                                data_atualizacao = veiculo[2]

                                media = (original + paralelo) / 2
                                info_categoria = calcular_categoria(media)

                                categoria = info_categoria["categoria"]
                                percentual_base = info_categoria["percentual"]
                                classe_categoria = info_categoria["classe"]
                                icone_categoria = info_categoria["icone"]

                                percentual_final = percentual_base + ((avarias - 1) * 10)
                                valor_calculado = media * (percentual_final / 100)
                                teto = obter_teto(avarias)
                                valor_final = min(valor_calculado, teto)

                                # ✅ Salvar consulta no histórico
                                try:
                                    conn = sqlite3.connect(DB)
                                    cursor = conn.cursor()

                                    cursor.execute("""
                                    INSERT INTO consultas (
                                        marca, modelo, ano, original, paralelo,
                                        media, categoria, percentual, avarias,
                                        valor_final, data_consulta
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (
                                        marca, modelo, ano, original, paralelo,
                                        media, categoria, percentual_final, avarias,
                                        valor_final, datetime.now().strftime("%d/%m/%Y %H:%M")
                                    ))

                                    conn.commit()
                                    conn.close()

                                    logger.info(f"Consulta registrada: {marca} {modelo} {ano}")

                                except sqlite3.Error as e:
                                    logger.error(f"Erro ao salvar consulta: {e}")
                                    mensagem = "Erro ao salvar consulta. Tente novamente."
                                    tipo_erro = "erro"

                                resultado = {
                                    "original": original,
                                    "paralelo": paralelo,
                                    "media": media,
                                    "categoria": categoria,
                                    "classe_categoria": classe_categoria,
                                    "icone_categoria": icone_categoria,
                                    "percentual": percentual_final,
                                    "teto": teto,
                                    "valor_final": valor_final,
                                    "data_atualizacao": data_atualizacao
                                }
                            else:
                                mensagem = f"Veículo não encontrado: {marca} {modelo} {ano}"
                                tipo_erro = "aviso"

        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            mensagem = "Ocorreu um erro inesperado. Tente novamente."
            tipo_erro = "erro"

    return render_template(
        "index.html",
        resultado=resultado,
        mensagem=mensagem,
        tipo_erro=tipo_erro
    )


# ============================================================
# ROTAS - HISTÓRICO
# ============================================================

@app.route("/historico")
@limiter.limit("20 per minute")
def historico():
    """Retorna histórico com paginação"""
    try:
        # ✅ Paginação
        pagina = request.args.get("pagina", 1, type=int)
        itens_por_pagina = 10
        offset = (pagina - 1) * itens_por_pagina

        conn = sqlite3.connect(DB)
        cursor = conn.cursor()

        # Total de registros
        cursor.execute("SELECT COUNT(*) FROM consultas")
        total_registros = cursor.fetchone()[0]
        total_paginas = (total_registros + itens_por_pagina - 1) // itens_por_pagina

        # Validar página
        if pagina < 1 or pagina > max(1, total_paginas):
            pagina = 1
            offset = 0

        # Buscar dados
        cursor.execute("""
        SELECT id, data_consulta, marca, modelo, ano, media, valor_final
        FROM consultas
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """, (itens_por_pagina, offset))

        dados = cursor.fetchall()
        conn.close()

        return render_template(
            "historico.html",
            dados=dados,
            pagina=pagina,
            total_paginas=total_paginas,
            total_registros=total_registros
        )

    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar histórico: {e}")
        return render_template(
            "historico.html",
            dados=[],
            mensagem="Erro ao carregar histórico",
            pagina=1,
            total_paginas=0,
            total_registros=0
        )


# ============================================================
# EXPORTAR PDF
# ============================================================

@app.route("/exportar-pdf")
@limiter.limit("5 per minute")
def exportar_pdf():
    """Exporta histórico em PDF"""
    try:
        # Buscar dados
        conn = sqlite3.connect(DB)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT id, data_consulta, marca, modelo, ano, media, valor_final
        FROM consultas
        ORDER BY id DESC
        LIMIT 100
        """)

        dados = cursor.fetchall()
        conn.close()

        if not dados:
            return "Nenhum dado para exportar", 404

        # Criar PDF em memória
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
        )

        # Elementos do PDF
        elements = []
        styles = getSampleStyleSheet()

        # Título
        titulo_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#0d6efd'),
            spaceAfter=10,
            alignment=1,
            fontName='Helvetica-Bold',
        )

        titulo = Paragraph(
            "Histórico de Consultas - Para-brisas",
            titulo_style
        )
        elements.append(titulo)

        # Subtítulo com data
        subtitulo_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=1,
        )

        data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M")
        subtitulo = Paragraph(
            f"Gerado em {data_geracao}",
            subtitulo_style
        )
        elements.append(subtitulo)
        elements.append(Spacer(1, 0.3 * inch))

        # Preparar dados da tabela
        dados_tabela = [
            ['Data', 'Marca', 'Modelo', 'Ano', 'Média', 'Valor Final']
        ]

        for item in dados:
            dados_tabela.append([
                item[1],
                item[2],
                item[3],
                item[4],
                f"R$ {item[5]:.2f}",
                f"R$ {item[6]:.2f}",
            ])

        # Criar tabela
        tabela = Table(dados_tabela, colWidths=[1.2 * inch, 1 * inch, 1 * inch, 0.6 * inch, 1.2 * inch, 1.2 * inch])

        # Estilizar tabela
        tabela.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dbeafe')),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (4, 1), (5, -1), 'RIGHT'),
            ('FONTNAME', (4, 0), (5, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (4, 1), (5, -1), colors.HexColor('#0d6efd')),
        ]))

        elements.append(tabela)

        # Rodapé
        elements.append(Spacer(1, 0.3 * inch))
        rodape_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            alignment=1,
        )
        rodape = Paragraph(
            f"Sistema Inteligente de Consulta de Reparo de Para-brisas © 2026<br/>Total de registros: {len(dados)}",
            rodape_style
        )
        elements.append(rodape)

        # Gerar PDF
        doc.build(elements)
        buffer.seek(0)

        logger.info(f"PDF exportado com sucesso: {len(dados)} registros")

        # Retornar PDF como download
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"historico_parabrisas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

    except Exception as e:
        logger.error(f"Erro ao exportar PDF: {e}")
        return render_template(
            "erro.html",
            mensagem="Erro ao gerar PDF. Tente novamente."
        ), 500


# ============================================================
# TRATAMENTO DE ERROS
# ============================================================

@app.errorhandler(429)
def ratelimit_handler(e):
    """Trata limite de requisições"""
    logger.warning(f"Rate limit excedido: {get_remote_address()}")
    return render_template("erro.html", mensagem="Muitas requisições. Tente novamente em alguns instantes."), 429


@app.errorhandler(404)
def pagina_nao_encontrada(e):
    """Trata página não encontrada"""
    return render_template("erro.html", mensagem="Página não encontrada"), 404


@app.errorhandler(500)
def erro_interno(e):
    """Trata erro interno"""
    logger.error(f"Erro interno do servidor: {e}")
    return render_template("erro.html", mensagem="Erro interno do servidor"), 500


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":
    
# Chamar na inicialização
inicializar_banco_se_necessario()
    try:
        criar_banco()
        debug_mode = app.config['DEBUG']

        logger.info(f"Iniciando aplicação (Debug: {debug_mode})")

        app.run(
            host="0.0.0.0",
            port=int(os.getenv("PORT", 5000)),
            debug=debug_mode
        )
    except Exception as e:
        logger.critical(f"Erro ao iniciar aplicação: {e}")
        raise