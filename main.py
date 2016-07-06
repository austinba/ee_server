# Hooks
# Session
# Error Handling
# Testing
# 
import eventlet
eventlet.monkey_patch()
import traceback
from flask import Flask, request, render_template
from flask_socketio import SocketIO, send, emit, join_room
import requests
import numpy as np
import random
import datetime

DEFAULT_PLAYER_MASS = 100
DEFAULT_BOOST_COST = 2.5
BOARD_WIDTH = 250
BOARD_HEIGHT = 250
MIN_PLAYERS_ZOMBIE_THRESHOLD = 25

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'

# Absolute path to the configuration file
app.config.from_envvar('APP_CONFIG_FILE')

socketio = SocketIO(app, async_mode='eventlet')

user_count = 0
current_zombie_id = 0
food = {}
obstacles = {}
players = {}
clients = {}

terrain = None

@app.route('/')
def index():
    return 'Welcome to Ethereal Epoch'

# Response from field-objects service
@app.route('/send_field_objects', methods=['POST'])
def field_object_creator(): 
    food = request.json["food"]
    obstacles = request.json["obstacles"]
    socketio.emit('field_objects',
                  {'food': food, 
                   'obstacles': obstacles})
    return 'Ok'

# Helper function to get all player information
def get_all_players_on_start(): 
    players = requests.get(app.config['DB_URL'] + '/users/get_all')
    for player in players: 
        clients[player['id']]
        emit('requestPosition', {},  room=player['id'])
        emit('spawn', {'id': player['id'], 'mass': player['mass']}, room=request.sid)

# On new client connection, create food, obstacles, landscape, and inialize player (on new client and others)
@socketio.on('connect')
def on_connect():
    global terrain, players, clients
    print('NEW CONNECTION: ', request.sid)

    # Request for the terrain
    if terrain == None:
        seed = datetime.datetime.now()
        seed = seed.hour + 24 * (seed.day + 31 * seed.month) * 4352 + 32454354
        terrain = requests.get(app.config['TERRAIN_URL'] +
           '/get_landscape?width=' + str(BOARD_WIDTH) +
           '&height=' + str(BOARD_HEIGHT) +
           '&seed=' + str(seed)).json()
    # print('terrain', terrain)
    
    # Note to self: make sure this returns in time on the first request
    socketio.emit('landscape', {'terrain': list(terrain)}, room=request.sid)
    # Request for field-objects: Response dealt with above
    # requests.get(app.config['OBJECTS_URL'] + '/terrain_objects')

    # Spawn all other players into new player's screen (Must happen before initializing current player)
    playersList = requests.get(app.config['DB_URL'] + '/users/get_all').json()
    if playersList != None or playersList['message'] != None: 
        for player in playersList:
            print(player)
            players[player['id']] = player
            emit('spawn', {'id': player['id'], 'mass': player['mass']}, room=request.sid)
    print('players should exist', players)

    # players[request.sid] = {'mass': mass}
    clients[request.sid] = {'zombies': []}
    add_more_zombies()

def initialize_main_player(id):
    playerPositionX = random.random() * (BOARD_WIDTH - 20) + 10
    playerPositionZ = random.random() * (BOARD_HEIGHT - 20) + 10
    socketio.emit('initialize_main_player',
                  {'id': id,
                   'mass': DEFAULT_PLAYER_MASS,
                   'x': playerPositionX,
                   'z': playerPositionZ}, room=id)
    # Spawn new player on other clients
    emit('spawn', {'id': id,
                   'mass': DEFAULT_PLAYER_MASS}, broadcast=True, include_self=False)
    # print('players count: ' + str(len(players)))


def add_more_zombies():
    global current_zombie_id
    if len(clients) == 0:
        return
    # create up to 20 zombies
    for i in range(max(0, MIN_PLAYERS_ZOMBIE_THRESHOLD - len(players))):
        # Choose a random client to add the zombie to
        client_id_to_add_zombies_to = random.choice(list(clients.keys()))
        zombieMass = DEFAULT_PLAYER_MASS * (random.random() * 0.9 + 0.1)
        current_zombie_id += 1
        zombiePositionX = random.random() * (BOARD_WIDTH - 20) + 10
        zombiePositionZ = random.random() * (BOARD_HEIGHT - 20) + 10
        zombieID = current_zombie_id
        socketio.emit('initialize_zombie_player',
                      {'id': zombieID, 
                       'mass': zombieMass,
                       'x': zombiePositionX,
                       'z': zombiePositionZ}, room=client_id_to_add_zombies_to)
        players[zombieID]  = {'id': zombieID, 'mass': zombieMass}
        clients[client_id_to_add_zombies_to]['zombies'].append(zombieID)
        # Store zombie on assigned player 
        requests.post(app.config['DB_URL'] + '/users/add', json={'mass': DEFAULT_PLAYER_MASS, 'id': client_id_to_add_zombies_to, 'zombies': zombieID})
        # Store zombie as player
        requests.post(app.config['DB_URL'] + '/users/add', json={'mass': zombieMass, 'id': zombieID, 'zombies': None })
        
        emit('spawn', {'id': zombieID, 'mass': zombieMass}, broadcast=True, include_self=False) 
        print('finsihed spawning zombie ',  zombieID)
        print('players count: ' + str(len(players)))


# Updates all clients when one client changes direction
@socketio.on('look')
def share_user_look_direction(json):
    # print('look: ' + request.sid)  
    emit('otherPlayerLook', dict({'id': request.sid}, **json), broadcast=True, include_self=False)

# Updates all clients and reduces player mass when one client uses boost
@socketio.on('boost')
def share_user_boost_action(json):
    emit('otherPlayerBoost', {'id': request.sid}, broadcast=True, include_self=False)
    player = requests.get(app.config['DB_URL'] + '/users/' + request.sid)
    emit('playerMassUpdate', {'id': request.sid, 'mass': player['mass'] - DEFAULT_BOOST_COST})
    requests.post(app.config['DB_URL'] + '/users/add', json={'id': request.sid, 'mass': player['mass'] - DEFAULT_BOOST_COST })

# Updates other players on player state in regular intervals
@socketio.on('player_state_reconcile')
def relay_player_state(json):
    # print('relay player state', json)
    emit('otherPlayerStateInfo', json, broadcast=True, include_self=False)

# Message sent when a player is killed
@socketio.on('kill_player')
def kill(json): 
    id = json['id']
    print('player killed', json)
    emit('player_killed', {'id': id}, broadcast=True, include_self=True)
    players.pop(id, None)
    requests.get(app.config['DB_URL'] + '/users/delete' + id)
    add_more_zombies()

@socketio.on('initialize_main')
def initialize_main(json):
    initialize_main_player(request.sid)

    ## Create food
    ## Send Kill Player Signal

@socketio.on('eat')
def regenerate_food(json):
    print('food eaten', json)
    data = requests.get(app.config['OBJECTS_URL'] + '/update_object?type=food&id='+json.id)
    emit('eaten', data, broadcast=True)

@socketio.on('collision')
def regenerate_obstacle(json): 
    print('obstacle hit', json)
    data = requests.get(app.config['OBJECTS_URL'] + '/update_object?type=obstacle&id='+json.id)
    emit('collided', data, broadcast=True)


# disconnect 

@socketio.on('disconnect')
def disconnect():
    print('Client disconnected', request.sid)
    print('players count: ' + str(len(players)))
    emit('onEndSpawn', {'id': request.sid}, broadcast=True) # currently doens't de-render 
    for zombie in clients[request.sid].setdefault('zombies', []):
        emit('onEndSpawn', {'id': zombie}, broadcast=True) # currently doens't de-render 
        players.pop(zombie, None)
    players.pop(request.sid, None)
    clients.pop(request.sid, None)
    add_more_zombies()
    print('players count: ' + str(len(players)))
# error handling
@socketio.on_error()    
def error_handler(e):
    print('error', e, traceback.format_exc())
    pass

@socketio.on_error_default
def default_error_handler(e):
    print('error', e, traceback.format_exc())
    pass


if __name__ == '__main__':
    # socketio.run(app)
    eventlet.wsgi.server(eventlet.listen(('', 9000)), app, debug=True)
