# Comet AI Search & Generation

A modern AI-powered search and generation tool that provides intelligent responses, creative solutions, and image generation capabilities.

## Features

- 🔍 **AI-Powered Search** with web search integration
- 🎨 **Image Generation & Editing** using OpenAI's models
- 🤖 **Multiple AI Models** support (OpenRouter, OpenAI, Anthropic, Google)
- 🌐 **Web Search Integration** with Tavily API
- 📱 **Progressive Web App** (PWA) support
- 🌙 **Dark/Light Mode** toggle
- 📊 **Chart Generation** with Chart.js integration
- 💬 **Streaming Responses** for real-time interaction

## Supported AI Models

### OpenAI Models
- GPT Image 1 (Image generation and editing)

### OpenRouter Models
- Google Gemini 2.5 Pro Preview
- Google Gemini 2.5 Flash Preview (with thinking)
- Perplexity Sonar Reasoning Pro
- OpenAI GPT-4.1
- OpenAI GPT-4.5 Preview
- OpenAI Codex Mini
- Anthropic Claude Sonnet 4
- Anthropic Claude Opus 4

## Quick Start

### Prerequisites

- Python 3.8+
- API keys for the services you want to use

### Local Development

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd comet
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

5. **Open your browser**
   Navigate to `http://localhost:8080`

## Deployment on Vercel

### One-Click Deploy

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/your-username/comet)

### Manual Deployment

1. **Fork this repository**

2. **Connect to Vercel**
   - Go to [Vercel Dashboard](https://vercel.com/dashboard)
   - Click "New Project"
   - Import your forked repository

3. **Configure Environment Variables**
   In your Vercel project settings, add these environment variables:
   
   ```
   OPENAI_API_KEY=your_openai_api_key
   OPENROUTER_API_KEY=your_openrouter_api_key
   TAVILY_API_KEY=your_tavily_api_key
   APP_SITE_URL=https://your-app-domain.vercel.app
   APP_SITE_TITLE=Comet AI Search
   ```

4. **Deploy**
   - Click "Deploy"
   - Your app will be available at your Vercel domain

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Optional | For GPT Image 1 model |
| `OPENROUTER_API_KEY` | Optional | For OpenRouter models |
| `TAVILY_API_KEY` | Optional | For web search functionality |
| `APP_SITE_URL` | Optional | Your app's URL for OpenRouter |
| `APP_SITE_TITLE` | Optional | App title for OpenRouter |

**Note:** At least one of `OPENAI_API_KEY` or `OPENROUTER_API_KEY` is required.

## API Keys Setup

### OpenAI API Key
1. Visit [OpenAI Platform](https://platform.openai.com/account/api-keys)
2. Create a new API key
3. Add it to your environment variables

### OpenRouter API Key
1. Visit [OpenRouter](https://openrouter.ai/keys)
2. Create an account and generate an API key
3. Add it to your environment variables

### Tavily API Key (for web search)
1. Visit [Tavily](https://tavily.com/)
2. Sign up and get your API key
3. Add it to your environment variables

## File Structure

```
comet/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── vercel.json           # Vercel deployment configuration
├── .env.example          # Environment variables template
├── templates/
│   └── index.html        # Main HTML template
├── static/
│   ├── style.css         # Styles
│   ├── script.js         # Frontend JavaScript
│   ├── manifest.json     # PWA manifest
│   ├── sw.js            # Service worker
│   └── *.png            # Icons and images
└── README.md            # This file
```

## Features in Detail

### Web Search Integration
- Real-time web search using Tavily API
- Source citations with clickable links
- Fallback search strategies for better results

### Image Generation & Editing
- Generate images from text prompts
- Edit existing images with AI
- Support for PNG format
- Download generated/edited images

### Progressive Web App
- Installable on mobile devices
- Offline caching for static assets
- Responsive design for all screen sizes

### AI Model Support
- Multiple AI providers in one interface
- Automatic model-specific parameter optimization
- Streaming responses for real-time interaction

## Troubleshooting

### Common Issues

1. **No API keys configured**
   - Ensure at least one API key is set in environment variables
   - Check Vercel environment variables are properly configured

2. **Image generation not working**
   - Verify `OPENAI_API_KEY` is set and valid
   - Check OpenAI account has sufficient credits

3. **Web search not working**
   - Verify `TAVILY_API_KEY` is set and valid
   - Web search is optional and app works without it

4. **Deployment issues on Vercel**
   - Check build logs for errors
   - Ensure all required environment variables are set
   - Verify Python version compatibility

### Performance Optimization

- The app uses streaming responses for better user experience
- Static assets are cached using service workers
- Production logging is optimized for performance

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

If you encounter any issues or have questions:

1. Check the troubleshooting section above
2. Review the environment variables setup
3. Check the browser console for errors
4. Open an issue on GitHub with detailed information

## Acknowledgments

- OpenAI for GPT models and image generation
- OpenRouter for model access
- Tavily for web search capabilities
- Vercel for hosting platform
- All the open-source libraries used in this project 