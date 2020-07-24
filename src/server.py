import time
import markdown
import json
import jsonpickle
import markdown.extensions.fenced_code
import markdown.extensions.codehilite
import os
from pygments.formatters import HtmlFormatter
from flask import Flask, request, jsonify, send_file, Response
from pymongo import MongoClient
import uuid
from datetime import datetime
import threading
import sys


database = {
    #"url": "mongodb://mongodb:27017/", 
    "url": "mongodb://localhost:27017/",
    "name": "elm",
    "collection": "models"
}

path = {
    "output": "/zip/",
    "datasets": "/datasets/"
}

status = [
    { 'code': 0, 'description': 'Model uploaded'},
    { 'code': 1, 'description': 'File csv uploaded'},
    { 'code': 2, 'description': 'Send to elm'},
    { 'code': 3, 'description': 'Training', 'perc': 0},
    { 'code': 4, 'description': 'Done'}
]

app = Flask(__name__)
port = int(os.environ.get('PORT', 5000))

client = MongoClient(database['url'])
cursor = client[database['name']]
collection = cursor[database['collection']]


def answer(content, status):
    if(status != 200):
        content = { 'error': content }
    return jsonify(content), status


@app.route('/model', methods=['POST'])
def set_model():
    if (not request.data):
        return answer('No request contents', 400)
    if (not request.is_json):
        return answer('Request content not in JSON format', 400)
    try:
        jsonpickle.decode(request.data)
    except ValueError as e:
        return answer('Request format not in valid JSON: ' + e, 400)

    content = request.get_json()

    # verifico che richiesta abbia tutti i campi necessari
    '''
    model_parameters = ['e','p','s','o']
    for parameter in model_parameters:
        if not parameter in content:
            return answer("Missing parameter: '" + parameter + "'", 400)
    '''

    #aggiungo valori in risposta
    content['_id'] = str(uuid.uuid4())
    content['status'] = status[0]
    content['output'] = content['_id'] +'.zip'
    content['timestamp'] = str(datetime.now())

    #inserisco in mongodb
    try:
        collection.insert_one(content)
    except:
        return answer('Database not connected', 400)

    return answer(content, 200)


@app.route('/model/<id>', methods=['GET'])
def get_model(id):
    try:
        result = collection.find_one({'_id':id})
    except:
        return answer('Database not connected', 400)

    if not result:
        return answer('Model not existing', 400)

    return answer(result, 200)


@app.route('/model/<id>/trainingset', methods=['POST'])
def upload_csv(id):
    #verifico che vi sia il file csv
    if not request.files.get('file'):
        return answer("Missing csv file", 400)
    
    #verifico che vi siano i parametri necessari
    model_parameters = ['target_column','test_size']
    for parameter in model_parameters:
        if not parameter in request.form:
            return answer("Missing parameter: '" + parameter + "'", 400)

    #recupero da mongodb 
    try:
        result = collection.find_one({'_id':id})
    except:
        return answer('Database not connected', 400)

    #se id non esiste
    if not result:
        return answer("Model not existing", 400)

    #Salva il file csv con il nuovo nome
    try:
        file_name = result['_id']+'.csv'
        f = request.files['file']
        file_path = os.path.join(path['datasets'], file_name)
        f.save(file_path)
    except:
        return answer("Error uploading file csv", 400)


    #aggiungo configurazione dataset
    result['d'] = {}
    result['d']['path'] = path['datasets'] + file_name #
    result['d']['target_column'] = request.form['target_column']
    result['d']['test_size'] = float(request.form['test_size'])
    
    vector_parameter = ['skip_rows', 'skip_columns']
    for parameter in vector_parameter:
        if request.form.get(parameter):
            result['d'][parameter] = request.form.getlist(parameter)

    scalar_parameter = ['sep', 'decimal','categorical_multiclass']
    for parameter in scalar_parameter:
        if request.form.get(parameter):
            result['d'][parameter] = request.form.get(parameter)
    
    #aggiorno lo stato
    result['status'] = status[1]

    #aggiorno mongodb
    try:
        collection.update_one({'_id':id}, {'$set':result})
    except:
        return answer("Database not connected", 400)

    return answer(result, 200)


@app.route('/model/<id>', methods=['PUT'])
def training(id):
    if (not request.data):
        return answer('No request contents', 400)
    if (not request.is_json):
        return answer('Request content not in JSON format', 400)
    try:
        jsonpickle.decode(request.data)
    except ValueError as e:
        return answer('Request format not in valid JSON: ' + e, 400)

    content = request.get_json()

    #recupero modello da mongodb
    try:
        result = collection.find_one({'_id':id})
    except:
        return answer('Database not connected', 400)

    #verifico che modello esista
    if not result:
        return answer("Model not existing", 400)

    #verifico body
    if not content['evaluate']:
        return answer("Evaluate must be true to begin training", 400)

    #aggiorno stato e mongodb
    try:
        collection.update_one({'_id':id}, {'$set':{'status':status[2]}})
        result = collection.find_one({'_id':id})
    except:
        return answer('Database not connected', 400)

    # avvio thread per addestramento elm in parallelo
    import interface_elm
    thread = threading.Thread(target=interface_elm.int_elm, args=(id, app, collection, status, result, ))
    thread.start()

    return answer(result, 200)


@app.route('/model/<id>/<output>', methods=['GET'])
def download(id, output):
    #recupero modello da mongodb
    try:
        result = collection.find_one({'_id':id})
    except:
        return answer('Database not connected', 400)

    #verifico che modello sia addestrato
    if result['status']['code'] != 4:
        return answer("Model not trained yet", 400)

    path_zip = '..' + path['output'] + output

    return send_file(path_zip, as_attachment=True)


@app.errorhandler(404)
def notfound(error):
    return answer('Route not found', 404)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=port)