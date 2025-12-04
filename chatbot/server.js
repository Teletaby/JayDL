const express = require('express');
const { GoogleGenerativeAI } = require('@google/generative-ai');
const cors = require('cors');
const session = require('express-session');
require('dotenv').config();

const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(cors());

// Session Middleware Setup
app.use(session({
  secret: 'jaydl-chatbot-secret-key-2024',
  resave: false,
  saveUninitialized: true,
  cookie: { secure: false }
}));

const MODEL_NAME = "gemini-2.5-flash";
const API_KEY = process.env.API_KEY;

if (!API_KEY) {
  console.error('ERROR: API_KEY not found in environment variables');
  process.exit(1);
}

console.log('Using model:', MODEL_NAME);

// System prompt for the chatbot
const SYSTEM_PROMPT = `You are JayDL Assistant, a helpful AI chatbot for the JayDL media downloader platform. Your role is to:

1. **Help with music and social media trends**: Provide information about trending music, artists, songs, TikTok trends, Instagram trends, Twitter/X trends, and Spotify recommendations.

2. **Guide users on downloading**: Explain how to download from YouTube, TikTok, Instagram, Twitter, and Spotify using the JayDL platform.

3. **Social Media Knowledge**: Share insights about what's trending on different platforms.

4. **Music Recommendations**: Suggest music based on user preferences, mood, or genre.

5. **Technical Help**: Answer questions about JayDL features.

Be friendly, informative, and concise.`;

// Function to run the chat
async function runChat(userInput, sessionData) {
  try {
    console.log('[Chat] Initializing Gemini API...');
    
    if (!API_KEY) {
      throw new Error('API_KEY is not set. Check your .env file.');
    }
    
    const genAI = new GoogleGenerativeAI(API_KEY);
    console.log('[Chat] API client initialized');
    
    console.log('[Chat] Getting model:', MODEL_NAME);
    const model = genAI.getGenerativeModel({ model: MODEL_NAME });

    const generationConfig = {
      temperature: 0.7,
      topK: 40,
      topP: 0.95,
      maxOutputTokens: 1024,
    };

    console.log('[Chat] Starting chat session...');
    const chat = model.startChat({
      generationConfig,
      history: []
    });

    console.log('[Chat] Sending message to API:', userInput.substring(0, 50) + '...');
    const result = await chat.sendMessage(userInput);
    
    console.log('[Chat] Got response from API');
    const response = result.response;
    
    if (!response) {
      throw new Error('Empty response from Gemini API');
    }
    
    const responseText = response.text();
    console.log('[Chat] Response text retrieved successfully, length:', responseText.length);

    return {
      success: true,
      response: responseText
    };
  } catch (error) {
    console.error('[Chat] Error occurred:', error.message);
    console.error('[Chat] Error code:', error.code);
    console.error('[Chat] Error status:', error.status);
    
    // Return a user-friendly error message
    let errorMessage = error.message;
    
    if (error.message.includes('API_KEY')) {
      errorMessage = 'Chatbot is not properly configured. Please check API credentials.';
    } else if (error.message.includes('timeout')) {
      errorMessage = 'Request took too long. Please try again.';
    } else if (error.message.includes('429')) {
      errorMessage = 'Too many requests. Please wait a moment and try again.';
    } else if (error.message.includes('403')) {
      errorMessage = 'API access denied. Please check your API key.';
    }
    
    return {
      success: false,
      response: errorMessage,
      error: 'Chat Error'
    };
  }
}

app.get('/', (req, res) => {
  res.json({
    success: true,
    message: 'JayDL Chatbot API is running',
    version: '1.0.0',
    endpoints: {
      chat: 'POST /chat'
    }
  });
});


app.post('/chat', async (req, res) => {
  try {
    console.log('Received chat request body:', JSON.stringify(req.body).substring(0, 100));
    const userInput = req.body?.userInput;
    
    if (!userInput) {
      console.log('No userInput provided');
      return res.status(400).json({
        success: false,
        error: 'Invalid request body - userInput is required'
      });
    }

    console.log('Processing message:', userInput.substring(0, 50) + '...');
    
    // Set a timeout for the chat request (25 seconds to leave room for network latency)
    const timeoutPromise = new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Chat request timeout - took too long to get response')), 25000)
    );
    
    const chatPromise = runChat(userInput, req.session || {});
    const result = await Promise.race([chatPromise, timeoutPromise]);

    console.log('Sending response - success:', result.success);
    res.json(result);
  } catch (error) {
    console.error('Error in chat endpoint:', error.message);
    console.error('Error details:', error);
    res.status(500).json({
      success: false,
      response: error.message || 'Failed to get response from AI. Please try again.',
      error: 'Internal Server Error',
      message: error.message
    });
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(port, () => {
  console.log(`🤖 JayDL Chatbot server is running on http://localhost:${port}`);
  console.log(`📝 Chat endpoint: POST http://localhost:${port}/chat`);
  console.log(`💬 Send {"userInput": "your message"} to chat with the AI`);
});
