import os
import logging
from serpapi import GoogleSearch

# ============================================================
# CONFIGURAÇÃO
# ============================================================

logger = logging.getLogger(__name__)
API_KEY = os.getenv("SERPAPI_KEY")


# ============================================================
# VALIDAÇÃO
# ============================================================


def validar_api_key():
    """Valida se a API key foi configurada"""
    if not API_KEY:
        logger.error("SERPAPI_KEY não está configurada nas variáveis de ambiente")
        return False

    if len(API_KEY) < 10:
        logger.error("SERPAPI_KEY parece inválida (muito curta)")
        return False

    return True


# ============================================================
# BUSCA GOOGLE
# ============================================================

def pesquisar_google(texto):
    """
    Faz uma pesquisa no Google usando a SerpAPI.

    Args:
        texto (str): Termo de busca

    Returns:
        dict: Resultado da busca ou dicionário com erro

    Raises:
        ValueError: Se o texto de busca for inválido
        Exception: Se houver erro na API
    """

    try:
        # ✅ Validação de entrada
        if not texto or not isinstance(texto, str):
            raise ValueError("Texto de busca inválido")

        texto = texto.strip()

        if len(texto) < 3:
            raise ValueError("Texto de busca deve ter no mínimo 3 caracteres")

        if len(texto) > 200:
            raise ValueError("Texto de busca não pode exceder 200 caracteres")

        # ✅ Validação de API Key
        if not validar_api_key():
            return {
                "erro": "SERPAPI_KEY não configurada",
                "sucesso": False
            }

        # ✅ Parâmetros da busca
        parametros = {
            "engine": "google",
            "q": texto,
            "hl": "pt-br",
            "gl": "br",
            "api_key": API_KEY
        }

        logger.info(f"Iniciando busca Google: {texto[:50]}...")

        # ✅ Executar busca
        busca = GoogleSearch(parametros)
        resultado = busca.get_dict()

        # ✅ Validar resposta
        if "error" in resultado:
            logger.error(f"Erro na API Google: {resultado['error']}")
            return {
                "erro": f"Erro na busca: {resultado.get('error', 'Desconhecido')}",
                "sucesso": False
            }

        logger.info("Busca concluída com sucesso")

        return {
            "sucesso": True,
            "resultado": resultado
        }

    except ValueError as e:
        logger.warning(f"Erro de validação: {e}")
        return {
            "erro": str(e),
            "sucesso": False
        }

    except Exception as e:
        logger.error(f"Erro inesperado na busca Google: {e}")
        return {
            "erro": f"Erro ao buscar: {str(e)[:100]}",
            "sucesso": False
        }


# ============================================================
# FUNÇÕES AUXILIARES (Futuras integrações)
# ============================================================

def buscar_preco_parabrisas(marca, modelo, ano):
    """
    Busca o preço de para-brisa para um veículo específico

    Uso futuro para integração com busca automática de preços
    """
    try:
        termo_busca = f"para-brisa {marca} {modelo} {ano} preço"
        return pesquisar_google(termo_busca)

    except Exception as e:
        logger.error(f"Erro ao buscar preço: {e}")
        return {
            "erro": "Não foi possível buscar o preço",
            "sucesso": False
        }


def buscar_fornecedores_parabrisas(marca, modelo):
    """
    Busca fornecedores de para-brisa para um veículo

    Uso futuro para listar fornecedores
    """
    try:
        termo_busca = f"fornecedor para-brisa {marca} {modelo} Brasil"
        return pesquisar_google(termo_busca)

    except Exception as e:
        logger.error(f"Erro ao buscar fornecedores: {e}")
        return {
            "erro": "Não foi possível buscar fornecedores",
            "sucesso": False
        }