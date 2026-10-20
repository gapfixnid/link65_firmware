"""JSON-lines transport for the linked firmware emulator. No live-device mode."""
import json
import sys
from firmware_model import FirmwareModel

model = FirmwareModel()
model.exchange(6)
model.exchange(16)
for line in sys.stdin:
    message = json.loads(line)
    try:
        if message.get('op') == 'matrix':
            model.set_matrix(message['rows'])
            value = []
        else:
            value = list(model.exchange(message['command'], bytes(message.get('args', []))))
        reply = {'id': message['id'], 'value': value}
    except Exception as error:
        reply = {'id': message['id'], 'error': type(error).__name__, 'message': str(error)}
    print(json.dumps(reply), flush=True)
