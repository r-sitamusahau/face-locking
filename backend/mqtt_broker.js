const aedes = require('aedes')();
const net = require('net');

const PORT = Number(process.env.MQTT_PORT || 1884);

const server = net.createServer(aedes.handle);

server.listen(PORT, '0.0.0.0', () => {
    console.log(`MQTT broker listening on port ${PORT}`);
});

aedes.on('client', (client) => {
    console.log(`MQTT client connected: ${client.id}`);
});

aedes.on('clientDisconnect', (client) => {
    console.log(`MQTT client disconnected: ${client.id}`);
});

aedes.on('publish', (packet, client) => {
    if (client) {
        console.log(`MQTT publish [${packet.topic}] from ${client.id}`);
    }
});
