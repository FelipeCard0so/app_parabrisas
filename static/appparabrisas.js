// appparabrisas.js - Funcionalidades do formulário

document.addEventListener('DOMContentLoaded', function() {
    // Validação básica do formulário
    const formulario = document.getElementById('formularioConsulta');
    
    if (formulario) {
        formulario.addEventListener('submit', function(e) {
            // Validação simples
            const marca = document.querySelector('input[name="marca"]');
            const modelo = document.querySelector('input[name="modelo"]');
            const ano = document.querySelector('input[name="ano"]');
            const avarias = document.querySelector('input[name="avarias"]');
            
            let erros = [];
            
            if (!marca || !marca.value.trim()) {
                erros.push('Marca é obrigatória');
                marca?.classList.add('campo-erro');
            }
            
            if (!modelo || !modelo.value.trim()) {
                erros.push('Modelo é obrigatório');
                modelo?.classList.add('campo-erro');
            }
            
            if (!ano || !ano.value.trim()) {
                erros.push('Ano é obrigatório');
                ano?.classList.add('campo-erro');
            }
            
            if (!avarias || !avarias.value) {
                erros.push('Quantidade de avarias é obrigatória');
                avarias?.classList.add('campo-erro');
            }
            
            // Se houver erros, previne submit
            if (erros.length > 0) {
                e.preventDefault();
                console.error('Erros de validação:', erros);
            }
        });
        
        // Remover classe de erro ao focar
        const inputs = formulario.querySelectorAll('input');
        inputs.forEach(input => {
            input.addEventListener('focus', function() {
                this.classList.remove('campo-erro');
            });
        });
    }
    
    // Fechar alertas
    const btnsFecha = document.querySelectorAll('.btn-fechar-alerta');
    btnsFecha.forEach(btn => {
        btn.addEventListener('click', function() {
            this.closest('.alerta')?.remove();
        });
    });
    
    // Filtros da tabela histórico
    const filtroMarca = document.getElementById('filtro-marca');
    const filtroModelo = document.getElementById('filtro-modelo');
    const filtroMin = document.getElementById('filtro-valor-min');
    const filtroMax = document.getElementById('filtro-valor-max');
    const btnFiltro = document.getElementById('btn-filtro');
    
    if (btnFiltro) {
        btnFiltro.addEventListener('click', function() {
            filtrarTabela();
        });
    }
    
    function filtrarTabela() {
        const marca = filtroMarca?.value.toLowerCase() || '';
        const modelo = filtroModelo?.value.toLowerCase() || '';
        const min = parseFloat(filtroMin?.value) || 0;
        const max = parseFloat(filtroMax?.value) || Infinity;
        
        const linhas = document.querySelectorAll('tbody tr');
        
        linhas.forEach(linha => {
            const marcaCell = linha.cells[0]?.textContent.toLowerCase() || '';
            const modeloCell = linha.cells[1]?.textContent.toLowerCase() || '';
            const valorCell = parseFloat(linha.cells[4]?.textContent.replace('R$ ', '').replace(',', '.')) || 0;
            
            const marcaMatch = !marca || marcaCell.includes(marca);
            const modeloMatch = !modelo || modeloCell.includes(modelo);
            const valorMatch = valorCell >= min && valorCell <= max;
            
            linha.style.display = marcaMatch && modeloMatch && valorMatch ? '' : 'none';
        });
    }
    
    // Exportar PDF
    const btnExportar = document.getElementById('btn-exportar-pdf');
    if (btnExportar) {
        btnExportar.addEventListener('click', function() {
            window.location.href = '/exportar-pdf';
        });
    }
});
