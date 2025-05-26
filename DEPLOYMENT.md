# Deployment Guide for Comet AI Search

## Pre-Deployment Checklist

### 1. Environment Variables
Ensure all required environment variables are set in Vercel:

**Required (at least one):**
- `OPENAI_API_KEY` - For GPT Image 1 model
- `OPENROUTER_API_KEY` - For OpenRouter models

**Optional:**
- `TAVILY_API_KEY` - For web search functionality
- `APP_SITE_URL` - Your app's URL (auto-set by Vercel)
- `APP_SITE_TITLE` - App title for OpenRouter

### 2. Security Configuration
- ✅ Debug mode disabled in production
- ✅ Security headers configured
- ✅ Input validation implemented
- ✅ Error handling for production
- ✅ Logging configured appropriately

### 3. Performance Optimizations
- ✅ Static asset caching via service worker
- ✅ Streaming responses for better UX
- ✅ Optimized logging for production
- ✅ Proper error boundaries

## Vercel Deployment Steps

### Method 1: One-Click Deploy
1. Click the "Deploy with Vercel" button in README
2. Configure environment variables
3. Deploy

### Method 2: Manual Deployment
1. Fork the repository
2. Connect to Vercel dashboard
3. Import the project
4. Configure environment variables
5. Deploy

## Post-Deployment Verification

### 1. Health Check
Visit `https://your-app.vercel.app/health` to verify:
- App is running
- Environment is correctly detected
- API keys are configured

### 2. Functionality Tests
- [ ] Basic text generation works
- [ ] Image generation works (if OpenAI key configured)
- [ ] Web search works (if Tavily key configured)
- [ ] File upload works
- [ ] Dark/light mode toggle works
- [ ] PWA installation works

### 3. Performance Tests
- [ ] Page loads quickly
- [ ] Streaming responses work
- [ ] No console errors
- [ ] Mobile responsiveness

## Monitoring and Maintenance

### 1. Vercel Analytics
- Enable Vercel Analytics for performance monitoring
- Monitor function execution times
- Track error rates

### 2. Error Monitoring
- Check Vercel function logs for errors
- Monitor API usage and rate limits
- Set up alerts for critical failures

### 3. Regular Updates
- Keep dependencies updated
- Monitor API provider changes
- Update model configurations as needed

## Troubleshooting Common Issues

### 1. Environment Variables Not Working
- Verify variables are set in Vercel dashboard
- Check variable names match exactly
- Redeploy after adding variables

### 2. API Errors
- Verify API keys are valid and have sufficient credits
- Check API provider status pages
- Review rate limiting settings

### 3. Performance Issues
- Check function timeout settings (max 30s on Vercel)
- Monitor memory usage
- Optimize large file uploads

### 4. CORS Issues
- Verify domain configuration
- Check security headers
- Update CSP if needed

## Security Best Practices

### 1. API Key Management
- Never commit API keys to repository
- Use Vercel environment variables
- Rotate keys regularly
- Monitor usage for anomalies

### 2. Input Validation
- All user inputs are validated
- File size limits enforced
- Query length limits enforced

### 3. Security Headers
- CSP configured for production
- XSS protection enabled
- Frame options set to DENY
- Content type sniffing disabled

## Scaling Considerations

### 1. Vercel Limits
- Function timeout: 30 seconds
- Memory: 1024MB
- Concurrent executions: Based on plan

### 2. API Rate Limits
- OpenAI: Monitor usage and billing
- OpenRouter: Check provider-specific limits
- Tavily: Monitor search quota

### 3. Optimization Strategies
- Implement request caching where appropriate
- Use streaming for long responses
- Optimize image processing

## Backup and Recovery

### 1. Configuration Backup
- Document all environment variables
- Keep API key backups secure
- Version control all code changes

### 2. Monitoring Setup
- Set up uptime monitoring
- Configure error alerting
- Monitor API usage patterns

## Support and Maintenance

### 1. Regular Checks
- Weekly: Check error logs and performance
- Monthly: Review API usage and costs
- Quarterly: Update dependencies and security

### 2. User Feedback
- Monitor user reports
- Track feature usage
- Plan improvements based on feedback

## Emergency Procedures

### 1. Service Outage
1. Check Vercel status page
2. Verify API provider status
3. Check environment variables
4. Review recent deployments
5. Rollback if necessary

### 2. Security Incident
1. Rotate affected API keys immediately
2. Review access logs
3. Update security measures
4. Notify users if data affected

### 3. Performance Degradation
1. Check function logs for errors
2. Monitor API response times
3. Verify resource usage
4. Scale or optimize as needed 