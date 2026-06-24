const http = require('http');
const url = require('url');

const VERIFY_TOKEN = 'cmllverify';

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  
  if (req.method === 'GET' && parsedUrl.pathname === '/webhook') {
    const mode = parsedUrl.query['hub.mode'];
    const token = parsedUrl.query['hub.verify_token'];
    const challenge = parsedUrl.query['hub.challenge'];
    
    if (mode === 'subscribe' && token === VERIFY_TOKEN) {
      console.log('Webhook verified!');
      res.writeHead(200);
      res.end(challenge);
    } else {
      res.writeHead(403);
      res.end('Forbidden');
    }
  } else if (req.method === 'POST' && parsedUrl.pathname === '/webhook') {
    res.writeHead(200);
    res.end('OK');
  } else {
    res.writeHead(200);
    res.end('CMLL Webhook is running!');
  }
});

server.listen(process.env.PORT || 3000, () => {
  console.log('Server running');
});
