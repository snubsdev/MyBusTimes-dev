import requests
import ipaddress
from functools import lru_cache

CLOUDFLARE_IPV4_URL = "https://www.cloudflare.com/ips-v4"
CLOUDFLARE_IPV6_URL = "https://www.cloudflare.com/ips-v6"

@lru_cache(maxsize=1)
def get_cloudflare_networks():
    ipv4_text = requests.get(CLOUDFLARE_IPV4_URL, timeout=5).text.strip().splitlines()
    ipv6_text = requests.get(CLOUDFLARE_IPV6_URL, timeout=5).text.strip().splitlines()

    ipv4_nets = [ipaddress.ip_network(cidr) for cidr in ipv4_text]
    ipv6_nets = [ipaddress.ip_network(cidr) for cidr in ipv6_text]

    return ipv4_nets, ipv6_nets
