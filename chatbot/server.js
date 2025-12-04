const express = require('express');
const { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold } = require('@google/generative-ai');
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

const MODEL_NAME = "gemini-pro";
const API_KEY = process.env.API_KEY;

if (!API_KEY) {
  console.error('ERROR: API_KEY not found in environment variables');
  process.exit(1);
}

// System prompt for the chatbot
const SYSTEM_PROMPT = `You are JayDL Assistant, a helpful AI chatbot for the JayDL media downloader platform. Your role is to:

1. **Help with music and social media trends**: Provide information about trending music, artists, songs, TikTok trends, Instagram trends, Twitter/X trends, and Spotify recommendations.

2. **Guide users on downloading**: Explain how to download from YouTube, TikTok, Instagram, Twitter, and Spotify using the JayDL platform.

3. **Social Media Knowledge**: Share insights about what's trending on different platforms:
   - YouTube: Trending videos, channels, and uploads
   - TikTok: Viral sounds, dances, and challenges
   - Instagram: Trending reels, stories, and content
   - Twitter/X: Trending topics and discussions
   - Spotify: Top playlists, artists, and songs

4. **Music Recommendations**: Suggest music based on user preferences, mood, or genre.

5. **Technical Help**: Answer questions about JayDL features like:
   - Different download formats (MP4, WebM, MP3)
   - Quality options
   - File sizes
   - Platform support

Be friendly, informative, and concise. If you don't know something, suggest the user check the platform directly or provide general guidance.

Current date: ${new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}`;

// Function to run the chat
async function runChat(userInput, sessionData) {
  const genAI = new GoogleGenerativeAI(API_KEY);
  const model = genAI.getGenerativeModel({ model: MODEL_NAME });

  const generationConfig = {
    temperature: 0.7,
    topK: 40,
    topP: 0.95,
    maxOutputTokens: 1024,
  };

  const safetySettings = [
    {
      category: HarmCategory.HARM_CATEGORY_HARASSMENT,
      threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    },
    {
      category: HarmCategory.HARM_CATEGORY_HATE_SPEECH,
      threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    },
    {
      category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
      threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    },
    {
      category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
      threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    }
  ];

  // Initialize chat history with system prompt
  let chatHistory = sessionData.chatHistory || [];
  
  // Add system prompt if this is the first message
  if (chatHistory.length === 0) {
    chatHistory.push({
      role: "user",
      parts: [{ text: "You are " + SYSTEM_PROMPT }]
    });
    chatHistory.push({
      role: "model",
      parts: [{ text: "I understand! I'm JayDL Assistant. I'm here to help you with music trends, social media insights, and downloading media from various platforms. How can I help you today?" }]
    });
  }

  let chat = model.startChat({
    generationConfig,
    safetySettings,
    history: chatHistory
  });

  try {
    const result = await chat.sendMessage(userInput);
    const response = result.response;
    const responseText = response.text();

    // Save updated chat history
    sessionData.chatHistory = chat.history;

    return {
      success: true,
      response: responseText
    };
  } catch (error) {
    console.error('Error in chat:', error);
    return {
      success: false,
      response: "I encountered an error processing your request. Please try again."
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
    const userInput = req.body?.userInput;
    
    if (!userInput) {
      return res.status(400).json({
        success: false,
        error: 'Invalid request body - userInput is required'
      });
    }

    // Initialize chat history in session if not present
    if (!req.session.chatHistory) {
      req.session.chatHistory = [];
    }

    const result = await runChat(userInput, req.session);

    res.json(result);
  } catch (error) {
    console.error('Error in chat endpoint:', error);
    res.status(500).json({
      success: false,
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
