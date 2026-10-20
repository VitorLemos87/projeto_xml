import hashlib
import difflib
import os
import re
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response
from lxml import etree

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TISS_SCHEMAS_DIR = os.path.join(BASE_DIR, 'schemas', 'tiss')

def calcular_hash_conteudo(texto, algoritmo='sha256'):
    hash_obj = hashlib.new(algoritmo)
    hash_obj.update(texto.encode('utf-8'))
    return hash_obj.hexdigest()

def calcular_hash_c14n(texto, algoritmo='sha256'):
    try:
        tree = etree.fromstring(texto.encode('utf-8'))
        c14n_bytes = etree.tostring(tree, method='c14n')
        hash_obj = hashlib.new(algoritmo)
        hash_obj.update(c14n_bytes)
        return hash_obj.hexdigest(), None
    except Exception as e:
        return None, str(e)

def validar_xml_com_xsd(xml_str, xsd_str):
    try:
        xsd_doc = etree.fromstring(xsd_str.encode('utf-8'))
        schema = etree.XMLSchema(xsd_doc)
        
        xml_doc = etree.fromstring(xml_str.encode('utf-8'))
        is_valid = schema.validate(xml_doc)
        
        erros = []
        if not is_valid:
            for error in schema.error_log:
                erros.append(f"Linha {error.line}: {error.message}")
                
        return is_valid, erros
    except etree.XMLSyntaxError as e:
        return False, [f"Erro de sintaxe no XML ou XSD: {str(e)}"]
    except etree.XMLSchemaParseError as e:
        return False, [f"Erro ao interpretar o Schema XSD: {str(e)}"]
    except Exception as e:
        return False, [f"Erro inesperado: {str(e)}"]

def _versoes_tiss_disponiveis():
    if not os.path.isdir(TISS_SCHEMAS_DIR):
        return []
    return [pasta for pasta in sorted(os.listdir(TISS_SCHEMAS_DIR))
            if re.fullmatch(r'\d+\.\d+\.\d+', pasta)]


@app.route('/', methods=['GET'])
def index():
    xml_exemplo = """<?xml version="1.0" encoding="UTF-8"?>
<produto>
    <nome>Teclado Mecânico</nome>
    <preco>250.00</preco>
</produto>"""
    return render_template('index.html', xml_content=xml_exemplo,
                           versoes_tiss=_versoes_tiss_disponiveis())

@app.route('/validar-hash', methods=['POST'])
def validar_hash():
    dados = request.get_json()
    xml_conteudo = dados.get('xml', '')
    hash_esperado = dados.get('hash_esperado', '').strip()
    algoritmo = dados.get('algoritmo', 'sha256')
    usar_c14n = dados.get('usar_c14n', False)

    try:
        etree.fromstring(xml_conteudo.encode('utf-8'))
        xml_valido = True
        erro_xml = None
    except etree.XMLSyntaxError as e:
        xml_valido = False
        erro_xml = str(e)

    if usar_c14n:
        hash_calculado, erro_c14n = calcular_hash_c14n(xml_conteudo, algoritmo)
        if erro_c14n:
            xml_valido = False
            erro_xml = f"Erro ao aplicar C14N: {erro_c14n}"
    else:
        hash_calculado = calcular_hash_conteudo(xml_conteudo, algoritmo)

    hash_batem = None
    if hash_esperado and hash_calculado:
        hash_batem = (hash_calculado.lower() == hash_esperado.lower())

    return jsonify({
        'xml_valido': xml_valido,
        'erro_xml': erro_xml,
        'hash_calculado': hash_calculado,
        'hash_esperado': hash_esperado,
        'hashes_coincidem': hash_batem
    })

@app.route('/validar-schema', methods=['POST'])
def validar_schema():
    dados = request.get_json()
    xml_conteudo = dados.get('xml', '')
    xsd_conteudo = dados.get('xsd', '')

    if not xsd_conteudo.strip():
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum conteúdo XSD foi fornecido.'}), 400

    valido, erros = validar_xml_com_xsd(xml_conteudo, xsd_conteudo)
    return jsonify({'sucesso': True, 'valido': valido, 'erros': erros})

@app.route('/validar-glosa', methods=['POST'])
def validar_glosa():
    """Valida a estrutura essencial de uma mensagem TISS de recurso de glosa."""
    dados = request.get_json(silent=True) or {}
    xml_conteudo = (dados.get('xml') or '').strip()

    if not xml_conteudo:
        return jsonify({'sucesso': False, 'valido': False,
                        'erros': ['Nenhum XML foi informado.'],
                        'avisos': []}), 400

    try:
        root = etree.fromstring(xml_conteudo.encode('utf-8'))
    except etree.XMLSyntaxError as exc:
        return jsonify({'sucesso': True, 'valido': False,
                        'erros': [f'XML inválido: {exc}'], 'avisos': []})

    def nome_local(elemento):
        return etree.QName(elemento).localname

    def encontrar(elemento, nome):
        achados = elemento.xpath('.//*[local-name()=$nome]', nome=nome)
        return achados[0] if achados else None

    def texto(elemento, nome):
        achado = encontrar(elemento, nome)
        return (achado.text or '').strip() if achado is not None else ''

    erros = []
    avisos = []

    if nome_local(root) != 'mensagemTISS':
        erros.append('O elemento raiz deve ser <mensagemTISS>.')

    cabecalho = encontrar(root, 'cabecalho')
    if cabecalho is None:
        erros.append('Bloco <cabecalho> não encontrado.')
    else:
        tipo = texto(cabecalho, 'tipoTransacao').upper()
        if tipo != 'RECURSO_GLOSA':
            erros.append('O <tipoTransacao> deve ser RECURSO_GLOSA.')
        if not texto(cabecalho, 'sequencialTransacao'):
            erros.append('O <sequencialTransacao> é obrigatório.')
        data_registro = texto(cabecalho, 'dataRegistroTransacao')
        if not data_registro:
            erros.append('A <dataRegistroTransacao> é obrigatória.')
        else:
            try:
                datetime.strptime(data_registro, '%Y-%m-%d')
            except ValueError:
                erros.append('A <dataRegistroTransacao> deve estar no formato AAAA-MM-DD.')
        if not texto(cabecalho, 'Padrao'):
            avisos.append('O campo <Padrao> não foi informado no cabeçalho.')

    guia = encontrar(root, 'guiaRecursoGlosa')
    if guia is None:
        erros.append('Bloco <guiaRecursoGlosa> não encontrado dentro de '
                     '<prestadorParaOperadora><recursoGlosa>.')
    else:
        campos_texto = [
            ('registroANS', 'registro ANS'),
            ('numeroGuiaRecGlosaPrestador', 'número da guia de recurso do prestador'),
            ('nomeOperadora', 'nome da operadora'),
            ('objetoRecurso', 'objeto do recurso'),
            ('valorTotalRecursado', 'valor total recursado'),
            ('dataRecurso', 'data do recurso'),
        ]
        for campo, rotulo in campos_texto:
            if not texto(guia, campo):
                erros.append(f'O campo <{campo}> ({rotulo}) é obrigatório.')

        for campo, rotulo in (('dadosContratado', 'dados do contratado'),
                              ('opcaoRecurso', 'opção do recurso')):
            if encontrar(guia, campo) is None:
                erros.append(f'O bloco <{campo}> ({rotulo}) é obrigatório.')

        objeto = texto(guia, 'objetoRecurso')
        if objeto and objeto not in ('1', '2', '3'):
            erros.append('O <objetoRecurso> deve ser 1, 2 ou 3.')

        valor = texto(guia, 'valorTotalRecursado').replace('.', '', 1).replace(',', '.')
        if valor:
            try:
                float(valor)
            except ValueError:
                erros.append('O <valorTotalRecursado> deve ser um valor numérico.')

        data_recurso = texto(guia, 'dataRecurso')
        if data_recurso:
            try:
                datetime.strptime(data_recurso, '%Y-%m-%d')
            except ValueError:
                erros.append('A <dataRecurso> deve estar no formato AAAA-MM-DD.')

        opcao = encontrar(guia, 'opcaoRecurso')
        if opcao is not None:
            if encontrar(opcao, 'recursoGuia') is None:
                erros.append('O bloco <opcaoRecurso> deve conter <recursoGuia>.')
            if encontrar(opcao, 'opcaoRecursoGuia') is None:
                erros.append('O bloco <recursoGuia> deve conter <opcaoRecursoGuia>.')
            itens = encontrar(opcao, 'itensGuia')
            completa = encontrar(opcao, 'recursoGuiaCompleta')
            if itens is None and completa is None:
                erros.append('Informe ao menos um <itensGuia> ou <recursoGuiaCompleta>.')

    hash_epilogo = encontrar(root, 'hash')
    if hash_epilogo is None or not (hash_epilogo.text or '').strip():
        avisos.append('O <epilogo><hash> está vazio; confira se o hash foi calculado.')

    return jsonify({
        'sucesso': True,
        'valido': not erros,
        'erros': erros,
        'avisos': avisos,
        'resumo': {
            'raiz': nome_local(root),
            'tipo_transacao': texto(root, 'tipoTransacao') if cabecalho is not None else '',
            'guia': texto(guia, 'numeroGuiaRecGlosaPrestador') if guia is not None else '',
        },
    })


@app.route('/atualizar-hash', methods=['POST'])
def atualizar_hash():
    """Calcula o hash sobre o XML com o epílogo vazio e grava o valor no próprio XML."""
    dados = request.get_json(silent=True) or {}
    xml_conteudo = (dados.get('xml') or '').strip()
    algoritmo = dados.get('algoritmo', 'md5')
    usar_c14n = bool(dados.get('usar_c14n'))

    if not xml_conteudo:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum XML foi informado.'}), 400

    try:
        root = etree.fromstring(xml_conteudo.encode('utf-8'))
    except etree.XMLSyntaxError as exc:
        return jsonify({'sucesso': False, 'mensagem': f'XML inválido: {exc}'}), 200

    if algoritmo not in hashlib.algorithms_available:
        return jsonify({'sucesso': False, 'mensagem': 'Algoritmo de hash não suportado.'}), 400

    epilogo = root.xpath('./*[local-name()="epilogo"]')
    if epilogo:
        epilogo = epilogo[0]
    else:
        ns = etree.QName(root).namespace
        epilogo = etree.SubElement(root, f'{{{ns}}}epilogo' if ns else 'epilogo')

    hashes = epilogo.xpath('./*[local-name()="hash"]')
    if hashes:
        hash_el = hashes[0]
    else:
        ns = etree.QName(root).namespace
        hash_el = etree.SubElement(epilogo, f'{{{ns}}}hash' if ns else 'hash')

    # O hash não pode incluir o próprio valor que está sendo calculado.
    hash_el.text = ''
    try:
        if usar_c14n:
            payload = etree.tostring(root, method='c14n')
        else:
            payload = etree.tostring(root, encoding='utf-8')
        digest = hashlib.new(algoritmo, payload).hexdigest()
    except Exception as exc:
        return jsonify({'sucesso': False, 'mensagem': f'Falha ao calcular o hash: {exc}'}), 200

    hash_el.text = digest
    novo_xml = etree.tostring(root, xml_declaration=True, encoding='UTF-8',
                              pretty_print=True).decode('utf-8')

    return jsonify({'sucesso': True, 'hash': digest, 'xml': novo_xml})


@app.route('/ajustar-recurso-glosa', methods=['POST'])
def ajustar_recurso_glosa():
    """Ajusta tags de um XML que já é recurso de glosa e devolve as linhas alteradas."""
    dados = request.get_json(silent=True) or {}
    xml_conteudo = (dados.get('xml') or '').strip()

    if not xml_conteudo:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum XML foi informado.'}), 400

    try:
        root = etree.fromstring(xml_conteudo.encode('utf-8'))
    except etree.XMLSyntaxError as exc:
        return jsonify({'sucesso': False, 'mensagem': f'XML inválido: {exc}'}), 200

    if etree.QName(root).localname != 'mensagemTISS':
        return jsonify({
            'sucesso': False,
            'mensagem': 'O XML não é uma mensagem TISS. Carregue um recurso de glosa para ajustar.',
        }), 200

    ns = etree.QName(root).namespace
    def tag(nome):
        return f'{{{ns}}}{nome}' if ns else nome

    def filho(elemento, nome):
        return elemento.find(tag(nome))

    def criar(elemento, nome):
        return etree.SubElement(elemento, tag(nome))

    alteracoes = []
    cabecalho = filho(root, 'cabecalho')
    if cabecalho is None:
        return jsonify({'sucesso': False,
                        'mensagem': 'O XML não possui o bloco <cabecalho>.'}), 200

    identificacao = filho(cabecalho, 'identificacaoTransacao')
    if identificacao is None:
        return jsonify({'sucesso': False,
                        'mensagem': 'O XML não possui <identificacaoTransacao>.'}), 200

    tipo = filho(identificacao, 'tipoTransacao')
    if tipo is None:
        tipo = criar(identificacao, 'tipoTransacao')
        alteracoes.append('Criado o campo tipoTransacao.')
    if (tipo.text or '').strip().upper() != 'RECURSO_GLOSA':
        anterior = (tipo.text or '').strip() or 'vazio'
        tipo.text = 'RECURSO_GLOSA'
        alteracoes.append(f'tipoTransacao alterado de "{anterior}" para "RECURSO_GLOSA".')

    pp = filho(root, 'prestadorParaOperadora')
    recurso = filho(pp, 'recursoGlosa') if pp is not None else None
    guia = filho(recurso, 'guiaRecursoGlosa') if recurso is not None else None
    if guia is None:
        return jsonify({
            'sucesso': False,
            'mensagem': 'O XML não possui a estrutura prestadorParaOperadora/recursoGlosa/guiaRecursoGlosa.',
        }), 200

    epilogo = filho(root, 'epilogo')
    if epilogo is None:
        epilogo = criar(root, 'epilogo')
        alteracoes.append('Criado o bloco <epilogo>.')
    hash_el = filho(epilogo, 'hash')
    if hash_el is None:
        hash_el = criar(epilogo, 'hash')
        hash_el.text = ''
        alteracoes.append('Criado o campo <epilogo><hash>.')
    elif not (hash_el.text or '').strip():
        alteracoes.append('O campo <epilogo><hash> está vazio e deve ser calculado na aba XML & Hash.')

    novo_xml = etree.tostring(root, xml_declaration=True, encoding='UTF-8',
                              pretty_print=True).decode('utf-8')
    antigas = xml_conteudo.splitlines()
    novas = novo_xml.splitlines()
    linhas = set()
    comparador = difflib.SequenceMatcher(None, antigas, novas)
    for operacao, _i1, _i2, j1, j2 in comparador.get_opcodes():
        if operacao != 'equal':
            linhas.update(range(j1 + 1, j2 + 1))

    return jsonify({
        'sucesso': True,
        'xml': novo_xml,
        'alteracoes': alteracoes,
        'linhas_alteradas': sorted(linhas),
        'mensagem': ('Nenhuma alteração necessária.' if not alteracoes else
                     'XML ajustado para recurso de glosa.'),
    })


@app.route('/validar-tiss', methods=['POST'])
def validar_tiss():
    """Detecta a versão TISS do XML e valida contra o XSD oficial embarcado."""
    dados = request.get_json(silent=True) or {}
    xml_conteudo = (dados.get('xml') or '').strip()

    if not xml_conteudo:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum XML foi informado.'}), 400

    try:
        root = etree.fromstring(xml_conteudo.encode('utf-8'))
    except etree.XMLSyntaxError as exc:
        return jsonify({'sucesso': False, 'mensagem': f'XML inválido: {exc}'}), 200

    def local_name(elemento):
        return etree.QName(elemento).localname

    def texto(nome):
        achados = root.xpath('.//*[local-name()=$nome]', nome=nome)
        return (achados[0].text or '').strip() if achados else ''

    versao_bruta = texto('Padrao') or (root.get('versao') or '')
    match = re.search(r'(\d{1,2})[._-]?(\d{2})[._-]?(\d{2})', versao_bruta)
    versao = f'{int(match.group(1))}.{match.group(2)}.{match.group(3)}' if match else ''

    versoes_disponiveis = _versoes_tiss_disponiveis()

    if dados.get('somente_versao'):
        return jsonify({
            'sucesso': True,
            'detectada': bool(versao),
            'suportada': bool(versao) and versao in versoes_disponiveis,
            'versao': versao,
            'versoes_disponiveis': versoes_disponiveis,
            'mensagem': ('Versão detectada.' if versao else
                         'Não foi possível identificar a versão no campo <Padrao>.'),
        })

    if not versao:
        return jsonify({
            'sucesso': True, 'detectada': False, 'suportada': False,
            'versao': '', 'versoes_disponiveis': versoes_disponiveis,
            'valido': False,
            'mensagem': 'Não foi possível identificar a versão no campo <Padrao> do cabeçalho.',
            'erros': [],
        })

    pasta_schema = os.path.join(TISS_SCHEMAS_DIR, versao)
    arquivo_schema = os.path.join(pasta_schema, f'tissV{versao.replace(".", "_")}.xsd')
    if not os.path.isfile(arquivo_schema):
        return jsonify({
            'sucesso': True, 'detectada': True, 'suportada': False,
            'versao': versao, 'versoes_disponiveis': versoes_disponiveis,
            'valido': False,
            'mensagem': f'Versão TISS {versao} identificada, mas o XSD dessa versão não está embarcado.',
            'erros': [],
        })

    try:
        schema_doc = etree.parse(arquivo_schema)
        schema = etree.XMLSchema(schema_doc)
    except (etree.XMLSchemaParseError, etree.XMLSyntaxError, OSError) as exc:
        return jsonify({
            'sucesso': False, 'detectada': True, 'suportada': True,
            'versao': versao, 'valido': False,
            'mensagem': f'Falha ao carregar o XSD da versão {versao}: {exc}',
            'erros': [],
        })

    valido = schema.validate(root)
    erros = []
    if not valido:
        for erro in schema.error_log:
            erros.append({
                'linha': erro.line,
                'coluna': erro.column,
                'mensagem': erro.message,
            })

    return jsonify({
        'sucesso': True,
        'detectada': True,
        'suportada': True,
        'versao': versao,
        'versao_xml': versao_bruta,
        'schema': os.path.relpath(arquivo_schema, BASE_DIR),
        'valido': valido,
        'erros': erros,
        'mensagem': 'XML válido para a versão TISS detectada.' if valido else
                    'O XML não atende ao XSD oficial desta versão.',
        'versoes_disponiveis': versoes_disponiveis,
    })


@app.route('/download', methods=['POST'])
def download():
    xml_conteudo = request.form.get('xml_download', '')
    filename = request.form.get('filename', 'arquivo_editado.xml')
    if not filename.endswith('.xml'):
        filename += '.xml'

    return Response(
        xml_conteudo,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

if __name__ == '__main__':
    app.run(debug=True)
