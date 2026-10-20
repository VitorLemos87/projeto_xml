import os
import hashlib
import re
from lxml import etree
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# Define o caminho base para a pasta de schemas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMAS_DIR = os.path.join(BASE_DIR, 'schemas', 'tiss')

# Página inicial básica com o formulário de envio (se você já tem um HTML, pode ignorar essa rota)
@app.route('/')
def index():
    return '''
    <!doctype html>
    <title>Validador TISS</title>
    <h1>Carregar XML TISS</h1>
    <form action="/validar" method="post" enctype="multipart/form-data">
      <input type="file" name="file" accept=".xml">
      <input type="submit" value="Validar">
    </form>
    '''

@app.route('/validar', methods=['POST'])
def validar_xml():
    # 1. Verifica se o arquivo foi enviado
    if 'file' not in request.files:
        return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado."}), 400
    
    arquivo = request.files['file']
    if arquivo.filename == '':
        return jsonify({"status": "erro", "mensagem": "Nenhum arquivo selecionado."}), 400

    # 2. Lê o conteúdo do arquivo (TISS geralmente usa ISO-8859-1)
    xml_content = arquivo.read()
    
    try:
        xml_str = xml_content.decode('iso-8859-1', errors='ignore')
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao ler o arquivo: {str(e)}"}), 400

    # 3. Identifica a versão do XML (Tag <ans:Padrao>)
    match_versao = re.search(r'<ans:Padrao>(.*?)</ans:Padrao>', xml_str)
    if not match_versao:
        return jsonify({"status": "erro", "mensagem": "Tag <ans:Padrao> não encontrada no XML."}), 400
    
    versao = match_versao.group(1) # Ex: "4.01.00" ou "4.03.00"
    
    # 4. Localiza e valida contra o XSD correto
    versao_formatada = versao.replace('.', '_')
    caminho_xsd = os.path.join(SCHEMAS_DIR, versao, f"tissV{versao_formatada}.xsd")

    if not os.path.exists(caminho_xsd):
        # Aviso se o XSD da versão não estiver na pasta do projeto
        return jsonify({
            "status": "aviso", 
            "mensagem": f"Versão {versao} detectada, mas o arquivo XSD não foi encontrado na pasta do servidor."
        }), 400

    try:
        xsd_doc = etree.parse(caminho_xsd)
        xsd = etree.XMLSchema(xsd_doc)
        xml_doc = etree.fromstring(xml_content)
        
        if not xsd.validate(xml_doc):
            erros = [f"Linha {e.line}: {e.message}" for e in xsd.error_log]
            return jsonify({
                "status": "erro",
                "mensagem": f"O XML não passou na validação XSD da versão {versao}.",
                "detalhes": erros
            }), 400
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao processar validação XSD: {str(e)}"}), 500

    # 5. Validação do Hash (Sem alterar o arquivo original)
    indice_epilogo = xml_str.find('<ans:epilogo>')
    if indice_epilogo == -1:
        return jsonify({"status": "erro", "mensagem": "Tag <ans:epilogo> não encontrada no XML."}), 400

    # Pega todo o XML desde o início até a tag <ans:epilogo> (não inclui o epílogo)
    xml_para_hash = xml_str[:indice_epilogo]
    
    # Calcula o MD5 esperado usando a codificação ISO-8859-1
    hash_calculado = hashlib.md5(xml_para_hash.encode('iso-8859-1')).hexdigest()

    # Pega o hash que veio dentro do XML
    match_hash = re.search(r'<ans:hash>(.*?)</ans:hash>', xml_str)
    if not match_hash:
        return jsonify({"status": "erro", "mensagem": "Tag <ans:hash> não encontrada no epílogo."}), 400
    
    hash_no_xml = match_hash.group(1)

    # 6. Compara os hashes
    if hash_calculado != hash_no_xml:
        return jsonify({
            "status": "erro_hash",
            "mensagem": "O hash do arquivo é inválido.",
            "hash_esperado_no_xml": hash_no_xml,
            "hash_calculado": hash_calculado
        }), 400

    # Se passou por tudo, retorna sucesso
    return jsonify({
        "status": "sucesso",
        "mensagem": f"Arquivo Válido! Versão {versao} e Hash estão corretos.",
        "versao": versao,
        "hash": hash_no_xml
    }), 200


if __name__ == '__main__':
    # O Render define a porta automaticamente na variável de ambiente PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)