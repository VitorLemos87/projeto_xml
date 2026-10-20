import hashlib
from flask import Flask, render_template, request, jsonify, Response
from lxml import etree

app = Flask(__name__)

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

@app.route('/', methods=['GET'])
def index():
    xml_exemplo = """<?xml version="1.0" encoding="UTF-8"?>
<produto>
    <nome>Teclado Mecânico</nome>
    <preco>250.00</preco>
</produto>"""
    return render_template('index.html', xml_content=xml_exemplo)

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
