const express = require('express');
const cors = require('cors');
require('dotenv').config();

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(cors());

// Test endpoint
app.post('/chat', async (req, res) => {
  try {
    const userInput = req.body?.userInput;
    
    if (!userInput) {
      return res.status(400).json({
        success: false,
        error: 'Invalid request body - userInput is required'
      });
    }

    console.log('Received message:', userInput);
    
    // Just echo the message for testing
    res.json({
      success: true,
      response: `You said: "${userInput}". The chatbot is working!`
    });
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({
      success: false,
      error: 'Internal Server Error',
      message: error.message
    });
  }
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(port, () => {
  console.log(`🤖 Test Chatbot server is running on http://localhost:${port}`);
  console.log(`📝 Chat endpoint: POST http://localhost:${port}/chat`);
});
