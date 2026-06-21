// ============================================================
// VALIDAÇÃO NO LADO DO CLIENTE
// ============================================================

console.log("✅ Sistema de validação carregado");

// ============================================================
// CLASSE VALIDADORA
// ============================================================

class ValidadorFormulario {

    constructor() {
        this.formulario = document.getElementById('formularioConsulta');
        this.campos = {
            marca: document.getElementById('marca'),
            modelo: document.getElementById('modelo'),
            ano: document.getElementById('ano'),
            avarias: document.getElementById('avarias')
        };
        this.erros = {};
        this.inicializar();
    }

    inicializar() {
        if (!this.formulario) {
            console.warn("Formulário não encontrado");
            return;
        }

        // Validação em tempo real
        Object.values(this.campos).forEach(campo => {
            if (campo) {
                campo.addEventListener('blur', (e) => this.validarCampo(e.target));
                campo.addEventListener('input', (e) => this.limparErro(e.target.id));
            }
        });

        // Validação ao enviar
        this.formulario.addEventListener('submit', (e) => this.validarFormulario(e));
    }

    // ============================================================
    // VALIDADORES INDIVIDUAIS
    // ============================================================

    validarMarca(valor) {
        const marca = valor.trim();

        if (!marca) {
            return { valido: false, erro: "Marca é obrigatória" };
        }

        if (marca.length < 2) {
            return { valido: false, erro: "Marca deve ter pelo menos 2 caracteres" };
        }

        if (marca.length > 50) {
            return { valido: false, erro: "Marca não pode exceder 50 caracteres" };
        }

        // Apenas letras, números, espaço e hífen
        if (!/^[a-zA-Z0-9\s\-]+$/.test(marca)) {
            return { valido: false, erro: "Marca contém caracteres inválidos" };
        }

        return { valido: true };
    }

    validarModelo(valor) {
        const modelo = valor.trim();

        if (!modelo) {
            return { valido: false, erro: "Modelo é obrigatório" };
        }

        if (modelo.length < 2) {
            return { valido: false, erro: "Modelo deve ter pelo menos 2 caracteres" };
        }

        if (modelo.length > 50) {
            return { valido: false, erro: "Modelo não pode exceder 50 caracteres" };
        }

        // Apenas letras, números, espaço, hífen e ponto
        if (!/^[a-zA-Z0-9\s\-\.]+$/.test(modelo)) {
            return { valido: false, erro: "Modelo contém caracteres inválidos" };
        }

        return { valido: true };
    }

    validarAno(valor) {
        const ano = parseInt(valor);
        const anoAtual = new Date().getFullYear();

        if (!valor) {
            return { valido: false, erro: "Ano é obrigatório" };
        }

        if (isNaN(ano)) {
            return { valido: false, erro: "Ano deve ser um número válido" };
        }

        if (ano < 1990) {
            return { valido: false, erro: "Ano não pode ser inferior a 1990" };
        }

        if (ano > anoAtual + 1) {
            return { valido: false, erro: `Ano não pode ser superior a ${anoAtual + 1}` };
        }

        return { valido: true };
    }

    validarAvarias(valor) {
        const avarias = parseInt(valor);

        if (!valor) {
            return { valido: false, erro: "Quantidade de avarias é obrigatória" };
        }

        if (isNaN(avarias)) {
            return { valido: false, erro: "Quantidade deve ser um número" };
        }

        if (avarias < 1) {
            return { valido: false, erro: "Deve ter no mínimo 1 avaria" };
        }

        if (avarias > 10) {
            return { valido: false, erro: "Máximo de 10 avarias permitido" };
        }

        return { valido: true };
    }

    // ============================================================
    // VALIDAÇÃO DE CAMPO INDIVIDUAL
    // ============================================================

    validarCampo(campo) {
        const id = campo.id;
        let resultado;

        switch (id) {
            case 'marca':
                resultado = this.validarMarca(campo.value);
                break;
            case 'modelo':
                resultado = this.validarModelo(campo.value);
                break;
            case 'ano':
                resultado = this.validarAno(campo.value);
                break;
            case 'avarias':
                resultado = this.validarAvarias(campo.value);
                break;
            default:
                return;
        }

        const elementoErro = document.getElementById(`erro-${id}`);

        if (!resultado.valido) {
            this.erros[id] = resultado.erro;
            if (elementoErro) {
                elementoErro.textContent = resultado.erro;
                elementoErro.style.display = 'block';
            }
            campo.classList.add('campo-erro');
            campo.classList.remove('campo-valido');
        } else {
            delete this.erros[id];
            if (elementoErro) {
                elementoErro.textContent = '';
                elementoErro.style.display = 'none';
            }
            campo.classList.remove('campo-erro');
            campo.classList.add('campo-valido');
        }
    }

    // ============================================================
    // VALIDAÇÃO DO FORMULÁRIO
    // ============================================================

    validarFormulario(evento) {
        evento.preventDefault();

        this.erros = {};

        // Validar todos os campos
        Object.entries(this.campos).forEach(([chave, campo]) => {
            if (campo) {
                this.validarCampo(campo);
            }
        });

        // Se não há erros, enviar
        if (Object.keys(this.erros).length === 0) {
            console.log("✅ Formulário válido. Enviando...");
            this.enviarFormulario();
        } else {
            console.warn("❌ Formulário com erros:", this.erros);
            this.mostrarErroGeral();
        }
    }

    // ============================================================
    // ENVIO DO FORMULÁRIO
    // ============================================================

    enviarFormulario() {
        const btnSubmit = document.getElementById('btnSubmit');
        const btnTexto = document.getElementById('btnTexto');
        const btnCarregando = document.getElementById('btnCarregando');

        // Mostrar estado de carregamento
        if (btnSubmit) {
            btnSubmit.disabled = true;
        }
        if (btnTexto) {
            btnTexto.style.display = 'none';
        }
        if (btnCarregando) {
            btnCarregando.style.display = 'inline';
        }

        // Enviar após breve delay
        setTimeout(() => {
            this.formulario.submit();
        }, 300);
    }

    // ============================================================
    // UTILITÁRIOS
    // ============================================================

    limparErro(idCampo) {
        const elementoErro = document.getElementById(`erro-${idCampo}`);
        if (elementoErro) {
            elementoErro.textContent = '';
            elementoErro.style.display = 'none';
        }
    }

    mostrarErroGeral() {
        const campo = Object.values(this.campos).find(c => c && c.classList.contains('campo-erro'));
        if (campo) {
            campo.focus();
            campo.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

// ============================================================
// INICIALIZAÇÃO
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    new ValidadorFormulario();

    // Fechar alertas ao clicar no X
    const botoesFecha = document.querySelectorAll('.btn-fechar-alerta');
    botoesFecha.forEach(botao => {
        botao.addEventListener('click', function() {
            this.parentElement.style.display = 'none';
        });
    });

    // Auto-fechar alertas de sucesso após 5 segundos
    const alertasSucesso = document.querySelectorAll('.alerta-sucesso');
    alertasSucesso.forEach(alerta => {
        setTimeout(() => {
            alerta.style.display = 'none';
        }, 5000);
    });

    // Scroll para resultado
    const resultado = document.getElementById('resultado');
    if (resultado) {
        setTimeout(() => {
            resultado.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 300);
    }
});