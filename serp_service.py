import os
import logging
from serpapi import GoogleSearch

logger = logging.getLogger(__name__)

API_KEY = os.getenv("SERPAPI_KEY")


def pesquisar_google(texto):

    if not API_KEY:
        logger.error("SERPAPI_KEY não configurada! Defina a variável de ambiente.")
        return {}

    logger.info(f"Iniciando busca Google: {texto}...")

    parametros = {
        "engine": "google",
        "q": texto,
        "hl": "pt-br",
        "gl": "br",
        "api_key": API_KEY
    }

    try:
        busca = GoogleSearch(parametros)
        resultado = busca.get_dict()

        # ✅ Log diagnóstico — mostra o que veio da API
        chaves = list(resultado.keys())
        logger.info(f"Chaves na resposta: {chaves}")

        # Verifica se há erro na resposta
        if "error" in resultado:
            logger.error(f"Erro da SerpAPI: {resultado['error']}")
            return {}

        # Verifica o status da busca
        metadata = resultado.get("search_metadata", {})
        status = metadata.get("status", "desconhecido")
        logger.info(f"Status da busca: {status}")

        organic = resultado.get("organic_results", [])
        shopping = resultado.get("shopping_results", [])
        logger.info(f"Busca concluída — organic: {len(organic)}, shopping: {len(shopping)}")

        return resultado

    except Exception as e:
        logger.error(f"Exceção na busca: {e}")
        return {}
