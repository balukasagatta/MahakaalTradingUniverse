"""
After cloudflared restarts, get new URL and update Upstox app via API
"""
import requests, os, time, subprocess

def get_cf_url():
    try:
        with open('/tmp/cf_tunnel.log') as f:
            for line in f:
                if 'trycloudflare.com' in line:
                    import re
                    m = re.search(r'https://[\w-]+\.trycloudflare\.com', line)
                    if m: return m.group(0)
    except: pass
    return None

def update_upstox_webhook(url):
    env = {}
    with open(os.path.expanduser('~/mahakaal/env.vars')) as f:
        for line in f:
            line = line.strip()
            if line and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    
    api_key    = env.get('UPSTOX_API_KEY')
    api_secret = env.get('UPSTOX_API_SECRET')
    token      = env.get('UPSTOX_ACCESS_TOKEN')
    
    webhook_url = url + '/upstox/token'
    print(f'Updating Upstox webhook to: {webhook_url}')
    
    # Save to env for reference
    subprocess.run(['sed', '-i', '/WEBHOOK_URL/d', os.path.expanduser('~/mahakaal/env.vars')])
    with open(os.path.expanduser('~/mahakaal/env.vars'), 'a') as f:
        f.write(f'\nWEBHOOK_URL={webhook_url}\n')
    
    print(f'Webhook URL saved. Update Upstox app manually with: {webhook_url}')

if __name__ == '__main__':
    time.sleep(10)
    url = get_cf_url()
    if url:
        update_upstox_webhook(url)
    else:
        print('Could not find cloudflare URL')
