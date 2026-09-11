/* Public catalog snapshot, reviewed 2026-09-10.
 * Sources: https://railcall.ai/integrations/
 * https://railcall-marketplace-lggm.onrender.com/listings?limit=100&offset=0
 * 35 direct + 412 reachable + 7 distinct Marketplace extensions = 454 entries.
 * Catalog identities, not tested accounts or 454 native connectors.
 */
(function(root) {
  'use strict';
  const direct = [
  [
    "Airtable",
    "CRM & Automation",
    "Spreadsheet-database for records & CRM",
    "airtable"
  ],
  [
    "Stripe",
    "Payments",
    "Payments, billing & subscriptions",
    "stripe"
  ],
  [
    "GitHub",
    "Code & Repos",
    "Git repos, issues & pull requests",
    "github"
  ],
  [
    "Notion",
    "Docs & Workspace",
    "Docs, wikis & databases",
    "notion"
  ],
  [
    "Email · SMTP",
    "Messaging",
    "Send email over your own SMTP",
    "email-smtp"
  ],
  [
    "Salesforce",
    "CRM & Automation",
    "Enterprise CRM & sales cloud",
    "salesforce"
  ],
  [
    "HubSpot",
    "CRM & Automation",
    "CRM, marketing & sales hub",
    "hubspot"
  ],
  [
    "Slack",
    "Comms",
    "Team chat & notifications",
    "slack"
  ],
  [
    "Discord",
    "Comms",
    "Community chat & bots",
    "discord"
  ],
  [
    "Telegram",
    "Comms",
    "Messaging & bot API",
    "telegram"
  ],
  [
    "Microsoft Graph",
    "Docs & Workspace",
    "Microsoft 365 — mail, calendar, Teams",
    "microsoft-graph"
  ],
  [
    "Google Drive",
    "Docs & Workspace",
    "Files & documents",
    "google-drive"
  ],
  [
    "Postgres",
    "Cloud & Deploy",
    "PostgreSQL database",
    "postgres"
  ],
  [
    "Supabase",
    "Cloud & Deploy",
    "Postgres backend + auth & storage",
    "supabase"
  ],
  [
    "Sentry",
    "Monitoring",
    "Error & crash monitoring",
    "sentry"
  ],
  [
    "Render",
    "Cloud & Deploy",
    "App & service hosting",
    "render"
  ],
  [
    "OpenAI",
    "LLMs",
    "GPT models & embeddings",
    "openai"
  ],
  [
    "Google Gemini",
    "LLMs",
    "Gemini models",
    "google-gemini"
  ],
  [
    "Mistral AI",
    "LLMs",
    "Open-weight LLMs",
    "mistral-ai"
  ],
  [
    "Cohere",
    "LLMs",
    "LLMs & rerank/embeddings",
    "cohere"
  ],
  [
    "Perplexity",
    "LLMs",
    "Answer engine API",
    "perplexity"
  ],
  [
    "DeepSeek",
    "LLMs",
    "Open reasoning LLMs",
    "deepseek"
  ],
  [
    "Webhook · incoming",
    "Webhooks",
    "Receive inbound events",
    "webhook-in"
  ],
  [
    "Webhook · outgoing",
    "Webhooks",
    "Fire outbound events",
    "webhook-out"
  ],
  [
    "Zapier",
    "Automation",
    "Automation platform",
    "zapier"
  ],
  [
    "Make",
    "Automation",
    "Visual automation platform",
    "make"
  ],
  [
    "n8n",
    "Automation",
    "Open-source workflow automation",
    "n8n"
  ],
  [
    "OpenRouter",
    "LLMs",
    "Model API gateway",
    "openrouter"
  ],
  [
    "Hugging Face",
    "LLMs",
    "Open-model platform",
    "hugging-face"
  ],
  [
    "Together AI",
    "LLMs",
    "Open-model inference",
    "together-ai"
  ],
  [
    "Fireworks AI",
    "LLMs",
    "Open-model inference",
    "fireworks-ai"
  ],
  [
    "Replicate",
    "LLMs",
    "Run & host ML models",
    "replicate"
  ],
  [
    "Anthropic · Claude",
    "LLMs",
    "Claude models",
    "anthropic"
  ],
  [
    "Ollama · local",
    "LLMs",
    "Run local models",
    "ollama"
  ],
  [
    "xAI · Grok",
    "LLMs",
    "Grok models",
    "xai-grok"
  ]
];
  const groups = {
  "Marketing & Analytics": "PostHog|Segment|Mixpanel|ActiveCampaign|Amplitude|Braze|Brevo|ConvertKit|Customer.io|Drip|FullStory|GetResponse|Google Analytics 4|Heap|Hotjar|Iterable|Klaviyo|LaunchDarkly|LogRocket|Mailchimp|MailerLite|Marketo|Matomo|Metabase|OneSignal|Optimizely|Pardot|Plausible|RudderStack|Snowplow|Statsig|beehiiv",
  "Databases": "Neon Postgres|PlanetScale|MySQL|MongoDB|Redis|Upstash Redis|Firestore|DynamoDB|Pinecone|Qdrant|Weaviate|Elasticsearch|BigQuery|Cassandra|ClickHouse|CockroachDB|Couchbase|Databricks|Fauna|InfluxDB|MotherDuck|Neo4j|Redshift|SingleStore|Snowflake|SurrealDB|TimescaleDB",
  "Comms & Messaging": "Microsoft Teams|Intercom|Zendesk|Aircall|Dialpad|Infobip|LINE|Mattermost|MessageBird|Plivo|RingCentral|Rocket.Chat|Sinch|Telnyx|Vonage|Webex|WhatsApp Business|Zoom|Zulip|SendGrid|Postmark|Resend|Twilio|Mailgun",
  "AI & Models": "Groq|LM Studio|AssemblyAI|Deepgram|ElevenLabs|Stability AI|AI21 Labs|AWS Bedrock|Anyscale|Azure OpenAI|Baseten|Cerebras|DeepInfra|Google Vertex AI|Hyperbolic|Jina AI|Lambda Labs|Modal|Novita AI|OctoAI|RunPod|SambaNova|Voyage AI|Writer",
  "HR & People": "15Five|ADP|Ashby|BambooHR|Culture Amp|Deel|Factorial|Greenhouse|Gusto|HiBob|Justworks|Lattice|Namely|Oyster|Paychex|Paylocity|Personio|Remote|Rippling|SmartRecruiters|TriNet|Workable|Workday",
  "E-commerce": "AfterShip|Amazon Seller|EasyPost|Ecwid|Faire|Medusa|PrestaShop|Printful|Printify|ShipStation|Shippo|Snipcart|Swell|Walmart|Wix|commercetools|eBay|BigCommerce|Etsy|Magento|Shopify|Squarespace Commerce|WooCommerce",
  "Docs & Workspace": "Confluence|Asana|Basecamp|Box|Canva|ClickUp|Coda|Dropbox|Egnyte|Evernote|Figma|GitBook|Guru|Lucidchart|Miro|OneDrive|SharePoint|Smartsheet|Todoist|Trello|Wrike|monday.com",
  "Payments & Fintech": "Adyen|Bill.com|Braintree|Chargebee|Checkout.com|Coinbase|Expensify|GoCardless|Gumroad|Lemon Squeezy|Mollie|Paddle|Razorpay|Recurly|Wise|Zuora|PayPal|Plaid|QuickBooks|Square|Xero",
  "Monitoring": "Bugsnag|Checkly|Cronitor|Dynatrace|Healthchecks.io|Honeycomb|Opsgenie|Pingdom|Prometheus|Raygun|Rollbar|Splunk|Statuspage|Sumo Logic|incident.io|Better Stack|UptimeRobot|Datadog|Grafana|New Relic|PagerDuty",
  "Cloud & Infra": "DigitalOcean|Cloudflare Workers|Alibaba Cloud|Appwrite|Heroku|Hetzner|IBM Cloud|Koyeb|Linode|Nhost|Oracle Cloud|PocketBase|Scaleway|Vultr|AWS|Google Cloud|Microsoft Azure|Railway|Fly.io|Cloudflare",
  "Auth & Security": "1Password|Doppler|HashiCorp Vault|Infisical|Cloudflare Zero Trust|Okta|Auth0|Clerk|Microsoft Entra ID|Bitwarden|Descope|Duo Security|Frontegg|Keycloak|Kinde|OneLogin|Stytch|SuperTokens|WorkOS",
  "CRM & Sales": "Apollo.io|Attio|Clari|Clearbit|Close|Copper|Gong|Hunter|Insightly|Keap|Outreach|Salesloft|SugarCRM|ZoomInfo|folk|Freshsales|Microsoft Dynamics 365|Pipedrive|Zoho CRM",
  "DevOps & CI/CD": "Docker Hub|Kubernetes|Tailscale|Ansible Automation|Argo CD|Azure DevOps|Buildkite|CodeSandbox|Gitea|Gitpod|Harness|Pulumi|Replit|Snyk|SonarQube|Sourcegraph|Terraform Cloud|ngrok",
  "Support": "Chatwoot|Crisp|Dixa|Drift|Front|Gladly|Groove|Hiver|Kayako|LiveAgent|LiveChat|Missive|Tidio|tawk.to|Freshdesk|Gorgias|Help Scout",
  "Voice & Media AI": "HeyGen|Ideogram|Leonardo AI|Luma AI|Murf|OpenAI Whisper|Pika|PlayHT|Recraft|Resemble AI|Runway|Suno|Synthesia",
  "Finance & Accounting": "Brex|FreeAgent|FreshBooks|MYOB|Mercury|NetSuite|Pennylane|Qonto|Ramp|Sage|Sage Intacct|Wave|Zoho Books",
  "Storage & CDN": "Cloudflare R2|Amazon S3|Google Cloud Storage|Azure Blob|Backblaze B2|Bunny.net|Cloudinary|Fastly|ImageKit|MinIO|Uploadcare|Wasabi|imgix",
  "Code & Repos": "GitHub Actions|Vercel|GitLab|Bitbucket|Linear|Jira|Netlify|Firebase|Postman|CircleCI|Jenkins|Retool",
  "Vector & Search": "Chroma|OpenSearch|Algolia|LanceDB|Marqo|Meilisearch|Milvus|Typesense|Vespa|pgvector|turbopuffer",
  "Analytics & BI": "Fathom Analytics|Hex|Lightdash|Looker|Mode|Pirsch|Power BI|Preset|Sigma|Tableau",
  "Scheduling & E-sign": "Acuity|Adobe Acrobat Sign|Cal.com|Calendly|DocuSign|Dropbox Sign|PandaDoc|SavvyCal|SignNow",
  "Browser & QA": "Playwright|Browserbase|Browserless|Cypress|Puppeteer|Insomnia|k6 Load Testing|Lighthouse",
  "Forms & Surveys": "Fillout|Formstack|Google Forms|Jotform|Paperform|SurveyMonkey|Tally|Typeform",
  "Maps & Location": "Geocodio|Google Maps|HERE|Mapbox|Radar"
};
  const extensions = [
  [
    "Zernio",
    "Social media",
    "ray9/zernio"
  ],
  [
    "Google Ads",
    "Marketing",
    "marcofgv/google-ads-airlock"
  ],
  [
    "Freelancer.com",
    "Freelance work",
    "marcofgv/freelancer-com"
  ],
  [
    "Odoo",
    "Business operations",
    "ray9/odoo"
  ],
  [
    "Feishu Bitable",
    "Documents & databases",
    "liyehaha/feishu-bitable"
  ],
  [
    "SingleOps",
    "Field operations",
    "sami666/singleops-browser"
  ],
  [
    "Google Sheets",
    "Documents",
    "sami666/google-sheets"
  ]
];
  const slug = name => name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  const directory = 'https://railcall.ai/integrations/';
  const catalog = direct.map(([name,category,summary,logo])=>({id:slug(name),name,category,summary,type:'Direct connector',logo:'https://railcall.ai/connection-logos/'+logo+'.svg',url:directory}))
    .concat(Object.entries(groups).flatMap(([category,names])=>names.split('|').map(name=>({id:slug(name),name,category,type:'Reachable app',summary:category+' · additional route setup required',url:directory}))))
    .concat(extensions.map(([name,category,path])=>({id:slug(name),name,category,type:'Marketplace extension',summary:category+' · published module',url:'https://railcall.ai/marketplace/'+path+'/'})));
  root.RailCallIntegrationCatalog=catalog;
  if(typeof module!=='undefined'&&module.exports)module.exports=catalog;
})(globalThis);
