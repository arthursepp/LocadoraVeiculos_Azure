import os
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from dotenv import load_dotenv

# -------------------------
# CONFIGURAÇÕES INICIAIS
# -------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "secret_key_provisoria")

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("CONTAINER_NAME")
CLIENTES_TABLE = os.getenv("CLIENTES_TABLE")
VEICULOS_TABLE = os.getenv("VEICULOS_TABLE")
LOCACOES_TABLE = os.getenv("LOCACOES_TABLE")

# -------------------------
# AZURE STORAGE CLIENTS
# -------------------------
blob_service_client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
table_service_client = TableServiceClient.from_connection_string(CONNECTION_STRING)

# Cria container e tabelas (se não existirem)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)
try:
    container_client.create_container()
except Exception:
    pass

for tbl in [CLIENTES_TABLE, VEICULOS_TABLE, LOCACOES_TABLE]:
    try:
        table_service_client.create_table_if_not_exists(tbl)
    except Exception:
        pass

clientes_table = table_service_client.get_table_client(CLIENTES_TABLE)
veiculos_table = table_service_client.get_table_client(VEICULOS_TABLE)
locacoes_table = table_service_client.get_table_client(LOCACOES_TABLE)

# -------------------------
# ROTAS PRINCIPAIS
# -------------------------

@app.route("/")
def index():
    """Página inicial"""
    return render_template("index.html")

@app.route("/admin")
def admin():
    """Painel de administração"""
    total_clientes = len(list(clientes_table.list_entities()))
    total_veiculos = len(list(veiculos_table.list_entities()))
    total_locacoes = len(list(locacoes_table.list_entities()))
    veiculos_disponiveis = len([v for v in veiculos_table.list_entities() if v.get("Disponivel", True)])
    
    return render_template("admin.html", 
                         total_clientes=total_clientes,
                         total_veiculos=total_veiculos,
                         total_locacoes=total_locacoes,
                         veiculos_disponiveis=veiculos_disponiveis)

# ---------- CLIENTES ----------
@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        telefone = request.form["telefone"]

        try:
            entity = {
                "PartitionKey": "CLIENTE",
                "RowKey": email,
                "Nome": nome,
                "Email": email,
                "Telefone": telefone,
                "DataCadastro": datetime.now(timezone.utc).isoformat()
            }
            clientes_table.create_entity(entity)
            flash("Cliente cadastrado com sucesso!", "success")
        except Exception as e:
            flash(f"Erro ao cadastrar cliente: {str(e)}", "error")

        return redirect(url_for("clientes"))

    # Busca e filtros
    busca = request.args.get("busca", "")
    clientes_list = list(clientes_table.list_entities())
    
    if busca:
        clientes_list = [c for c in clientes_list if busca.lower() in c["Nome"].lower() or busca.lower() in c["Email"].lower()]
    
    return render_template("clientes.html", clientes=clientes_list, busca=busca)

@app.route("/clientes/editar/<email>", methods=["GET", "POST"])
def editar_cliente(email):
    if request.method == "POST":
        nome = request.form["nome"]
        telefone = request.form["telefone"]
        
        try:
            entity = {
                "PartitionKey": "CLIENTE",
                "RowKey": email,
                "Nome": nome,
                "Email": email,
                "Telefone": telefone,
            }
            clientes_table.update_entity(entity)
            flash("Cliente atualizado com sucesso!", "success")
            return redirect(url_for("clientes"))
        except Exception as e:
            flash(f"Erro ao atualizar cliente: {str(e)}", "error")
    
    try:
        cliente = clientes_table.get_entity(partition_key="CLIENTE", row_key=email)
        return render_template("editar_cliente.html", cliente=cliente)
    except Exception as e:
        flash("Cliente não encontrado!", "error")
        return redirect(url_for("clientes"))

@app.route("/clientes/excluir/<email>")
def excluir_cliente(email):
    try:
        # Verificar se o cliente tem locações
        locacoes_cliente = list(locacoes_table.query_entities(
            query_filter=f"Cliente eq '{email}'"
        ))
        
        if locacoes_cliente:
            flash("Não é possível excluir cliente com locações ativas!", "error")
        else:
            clientes_table.delete_entity(partition_key="CLIENTE", row_key=email)
            flash("Cliente excluído com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir cliente: {str(e)}", "error")
    
    return redirect(url_for("clientes"))

@app.route("/cliente/<email>/historico")
def historico_cliente(email):
    try:
        cliente = clientes_table.get_entity(partition_key="CLIENTE", row_key=email)
        locacoes = list(locacoes_table.query_entities(
            query_filter=f"Cliente eq '{email}'"
        ))
        
        # Adicionar informações do veículo em cada locação
        for locacao in locacoes:
            try:
                veiculo = veiculos_table.get_entity(partition_key="VEICULO", row_key=locacao["Veiculo"])
                locacao["VeiculoInfo"] = veiculo
            except:
                locacao["VeiculoInfo"] = {"Marca": "N/A", "Modelo": "N/A"}
        
        return render_template("historico_cliente.html", cliente=cliente, locacoes=locacoes)
    except Exception as e:
        flash("Cliente não encontrado!", "error")
        return redirect(url_for("clientes"))

# ---------- VEÍCULOS ----------
@app.route("/veiculos", methods=["GET", "POST"])
def veiculos():
    if request.method == "POST":
        marca = request.form["marca"]
        modelo = request.form["modelo"]
        ano = request.form["ano"]
        placa = request.form["placa"]
        preco = request.form["preco"]
        file = request.files["foto"]

        blob_url = ""
        if file and file.filename:
            try:
                blob_client = container_client.get_blob_client(file.filename)
                blob_client.upload_blob(file, overwrite=True)
                blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{file.filename}"
            except Exception as e:
                flash(f"Erro ao fazer upload da imagem: {str(e)}", "error")

        try:
            entity = {
                "PartitionKey": "VEICULO",
                "RowKey": placa,
                "Marca": marca,
                "Modelo": modelo,
                "Ano": ano,
                "Preco": float(preco),
                "FotoUrl": blob_url,
                "Disponivel": True
            }
            veiculos_table.create_entity(entity)
            flash("Veículo cadastrado com sucesso!", "success")
        except Exception as e:
            flash(f"Erro ao cadastrar veículo: {str(e)}", "error")

        return redirect(url_for("veiculos"))

    # Filtros
    marca_filtro = request.args.get("marca", "")
    disponivel_filtro = request.args.get("disponivel", "")
    
    veiculos_list = list(veiculos_table.list_entities())
    
    if marca_filtro:
        veiculos_list = [v for v in veiculos_list if marca_filtro.lower() in v["Marca"].lower()]
    
    if disponivel_filtro:
        disponivel = disponivel_filtro == "true"
        veiculos_list = [v for v in veiculos_list if v.get("Disponivel", False) == disponivel]
    
    return render_template("veiculos.html", veiculos=veiculos_list, marca_filtro=marca_filtro, disponivel_filtro=disponivel_filtro)

@app.route("/veiculos/editar/<placa>", methods=["GET", "POST"])
def editar_veiculo(placa):
    if request.method == "POST":
        marca = request.form["marca"]
        modelo = request.form["modelo"]
        ano = request.form["ano"]
        preco = request.form["preco"]
        file = request.files["foto"]

        try:
            veiculo = veiculos_table.get_entity(partition_key="VEICULO", row_key=placa)
            
            blob_url = veiculo.get("FotoUrl", "")
            if file and file.filename:
                try:
                    blob_client = container_client.get_blob_client(file.filename)
                    blob_client.upload_blob(file, overwrite=True)
                    blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{file.filename}"
                except Exception as e:
                    flash(f"Erro ao fazer upload da imagem: {str(e)}", "error")

            entity = {
                "PartitionKey": "VEICULO",
                "RowKey": placa,
                "Marca": marca,
                "Modelo": modelo,
                "Ano": ano,
                "Preco": float(preco),
                "FotoUrl": blob_url,
                "Disponivel": veiculo.get("Disponivel", True)
            }
            veiculos_table.update_entity(entity)
            flash("Veículo atualizado com sucesso!", "success")
            return redirect(url_for("veiculos"))
        except Exception as e:
            flash(f"Erro ao atualizar veículo: {str(e)}", "error")
    
    try:
        veiculo = veiculos_table.get_entity(partition_key="VEICULO", row_key=placa)
        return render_template("editar_veiculo.html", veiculo=veiculo)
    except Exception as e:
        flash("Veículo não encontrado!", "error")
        return redirect(url_for("veiculos"))

@app.route("/veiculos/excluir/<placa>")
def excluir_veiculo(placa):
    try:
        # Verificar se o veículo tem locações
        locacoes_veiculo = list(locacoes_table.query_entities(
            query_filter=f"Veiculo eq '{placa}'"
        ))
        
        if locacoes_veiculo:
            flash("Não é possível excluir veículo com locações ativas!", "error")
        else:
            veiculos_table.delete_entity(partition_key="VEICULO", row_key=placa)
            flash("Veículo excluído com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir veículo: {str(e)}", "error")
    
    return redirect(url_for("veiculos"))

# ---------- LOCAÇÕES ----------
@app.route("/locacoes", methods=["GET", "POST"])
def locacoes():
    clientes_list = list(clientes_table.list_entities())
    veiculos_list = [v for v in veiculos_table.list_entities() if v.get("Disponivel", True)]

    if request.method == "POST":
        cliente = request.form["cliente"]
        veiculo = request.form["veiculo"]
        data_inicio = request.form["inicio"]
        data_fim = request.form["fim"]
        valor = request.form["valor"]

        try:
            entity = {
                "PartitionKey": "LOCACAO",
                "RowKey": f"{cliente}-{veiculo}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "Cliente": cliente,
                "Veiculo": veiculo,
                "DataInicio": data_inicio,
                "DataFim": data_fim,
                "Valor": float(valor),
                "Status": "Ativa"
            }

            locacoes_table.create_entity(entity)
            
            # Atualiza disponibilidade do veículo
            veiculo_ent = veiculos_table.get_entity(partition_key="VEICULO", row_key=veiculo)
            veiculo_ent["Disponivel"] = False
            veiculos_table.update_entity(veiculo_ent)
            
            flash("Locação criada com sucesso!", "success")
        except Exception as e:
            flash(f"Erro ao criar locação: {str(e)}", "error")

        return redirect(url_for("locacoes"))

    locacoes_list = list(locacoes_table.list_entities())
    
    # Adicionar informações do cliente e veículo em cada locação
    for locacao in locacoes_list:
        try:
            cliente_info = clientes_table.get_entity(partition_key="CLIENTE", row_key=locacao["Cliente"])
            locacao["ClienteInfo"] = cliente_info
        except:
            locacao["ClienteInfo"] = {"Nome": "N/A"}
        
        try:
            veiculo_info = veiculos_table.get_entity(partition_key="VEICULO", row_key=locacao["Veiculo"])
            locacao["VeiculoInfo"] = veiculo_info
        except:
            locacao["VeiculoInfo"] = {"Marca": "N/A", "Modelo": "N/A"}
    
    return render_template("locacoes.html", locacoes=locacoes_list, clientes=clientes_list, veiculos=veiculos_list)

@app.route("/locacoes/cancelar/<locacao_id>")
def cancelar_locacao(locacao_id):
    try:
        locacao = locacoes_table.get_entity(partition_key="LOCACAO", row_key=locacao_id)
        locacao["Status"] = "Cancelada"
        locacoes_table.update_entity(locacao)
        
        # Liberar veículo
        veiculo_ent = veiculos_table.get_entity(partition_key="VEICULO", row_key=locacao["Veiculo"])
        veiculo_ent["Disponivel"] = True
        veiculos_table.update_entity(veiculo_ent)
        
        flash("Locação cancelada com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao cancelar locação: {str(e)}", "error")
    
    return redirect(url_for("locacoes"))

@app.route("/locacoes/finalizar/<locacao_id>")
def finalizar_locacao(locacao_id):
    try:
        locacao = locacoes_table.get_entity(partition_key="LOCACAO", row_key=locacao_id)
        locacao["Status"] = "Finalizada"
        locacoes_table.update_entity(locacao)
        
        # Liberar veículo
        veiculo_ent = veiculos_table.get_entity(partition_key="VEICULO", row_key=locacao["Veiculo"])
        veiculo_ent["Disponivel"] = True
        veiculos_table.update_entity(veiculo_ent)
        
        flash("Locação finalizada com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao finalizar locação: {str(e)}", "error")
    
    return redirect(url_for("locacoes"))

# ---------- ÁREA DO CLIENTE ----------
@app.route("/area-cliente")
def area_cliente():
    """Página inicial da área do cliente"""
    return render_template("area_cliente.html")

@app.route("/area-cliente/historico", methods=["GET", "POST"])
def historico_pessoal():
    """Histórico de locações do cliente (simulação - normalmente teria login)"""
    email_cliente = request.form.get("email") if request.method == "POST" else request.args.get("email", "")
    cliente = None
    locacoes = []
    
    if email_cliente:
        try:
            cliente = clientes_table.get_entity(partition_key="CLIENTE", row_key=email_cliente)
            locacoes = list(locacoes_table.query_entities(
                query_filter=f"Cliente eq '{email_cliente}'"
            ))
            
            # Garantir que Valor seja float para todas as locações
            for locacao in locacoes:
                if isinstance(locacao.get("Valor"), str):
                    try:
                        locacao["Valor"] = float(locacao["Valor"])
                    except (ValueError, TypeError):
                        locacao["Valor"] = 0.0
            
            # Adicionar informações do veículo
            for locacao in locacoes:
                try:
                    veiculo = veiculos_table.get_entity(partition_key="VEICULO", row_key=locacao["Veiculo"])
                    locacao["VeiculoInfo"] = veiculo
                except:
                    locacao["VeiculoInfo"] = {"Marca": "N/A", "Modelo": "N/A"}
                    
        except Exception as e:
            flash("Cliente não encontrado!", "error")
    
    return render_template("historico_pessoal.html", cliente=cliente, locacoes=locacoes, email_cliente=email_cliente)

@app.route("/area-cliente/editar-dados", methods=["GET", "POST"])
def editar_dados_pessoais():
    """Edição de dados pessoais (simulação - normalmente teria login)"""
    
    if request.method == "POST":
        # Verificar se é para carregar dados ou salvar alterações
        if "carregar" in request.form:
            # Apenas carregar dados do cliente
            email_cliente = request.form.get("email", "")
        else:
            # Salvar alterações nos dados
            email_cliente = request.form.get("email_original", "")
            nome = request.form.get("nome", "")
            telefone = request.form.get("telefone", "")
            novo_email = request.form.get("novo_email", "")
            
            if email_cliente and nome and telefone and novo_email:
                try:
                    # Se mudou o email, precisa criar nova entidade e excluir a antiga
                    if novo_email != email_cliente:
                        # Verificar se novo email já existe
                        try:
                            clientes_table.get_entity(partition_key="CLIENTE", row_key=novo_email)
                            flash("Este email já está em uso!", "error")
                            return redirect(url_for("editar_dados_pessoais", email=email_cliente))
                        except:
                            pass
                        
                        # Criar nova entidade
                        entity = {
                            "PartitionKey": "CLIENTE",
                            "RowKey": novo_email,
                            "Nome": nome,
                            "Email": novo_email,
                            "Telefone": telefone,
                            "DataCadastro": datetime.now(timezone.utc).isoformat()
                        }
                        clientes_table.create_entity(entity)
                        
                        # Atualizar email nas locações
                        locacoes_cliente = list(locacoes_table.query_entities(
                            query_filter=f"Cliente eq '{email_cliente}'"
                        ))
                        for locacao in locacoes_cliente:
                            locacao["Cliente"] = novo_email
                            locacoes_table.update_entity(locacao)
                        
                        # Excluir entidade antiga
                        clientes_table.delete_entity(partition_key="CLIENTE", row_key=email_cliente)
                        
                        email_cliente = novo_email
                        flash("Dados atualizados com sucesso! Email alterado.", "success")
                    else:
                        # Apenas atualizar dados
                        entity = {
                            "PartitionKey": "CLIENTE",
                            "RowKey": email_cliente,
                            "Nome": nome,
                            "Email": email_cliente,
                            "Telefone": telefone,
                        }
                        clientes_table.update_entity(entity)
                        flash("Dados atualizados com sucesso!", "success")
                        
                except Exception as e:
                    flash(f"Erro ao atualizar dados: {str(e)}", "error")
    else:
        # Método GET - carregar por query parameter
        email_cliente = request.args.get("email", "")
    
    cliente = None
    if email_cliente:
        try:
            cliente = clientes_table.get_entity(partition_key="CLIENTE", row_key=email_cliente)
        except:
            flash("Cliente não encontrado!", "error")
    
    return render_template("editar_dados_pessoais.html", cliente=cliente, email_cliente=email_cliente)

if __name__ == "__main__":
    # Verifica se está rodando no Render
    port = int(os.environ.get("PORT", 5000))
    
    if os.getenv("RENDER"):
        # Produção no Render
        app.run(host="0.0.0.0", port=port)
    else:
        # Desenvolvimento local
        app.run(debug=True, host="0.0.0.0", port=port)