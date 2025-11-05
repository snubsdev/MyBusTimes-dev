import requests
import ipaddress
from functools import lru_cache

CLOUDFLARE_IPV4_URL = "https://www.cloudflare.com/ips-v4"
CLOUDFLARE_IPV6_URL = "https://www.cloudflare.com/ips-v6"

def is_cloudflare_ip(ip):
    ipv4_nets, ipv6_nets = get_cloudflare_networks()

    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False  # invalid IP, don't treat as CF but also don't ban it yet

    if ip_obj.version == 4:
        return any(ip_obj in net for net in ipv4_nets)
    else:
        return any(ip_obj in net for net in ipv6_nets)

@lru_cache(maxsize=1)
def get_cloudflare_networks():
    ipv4_text = requests.get(CLOUDFLARE_IPV4_URL, timeout=5).text.strip().splitlines()
    ipv6_text = requests.get(CLOUDFLARE_IPV6_URL, timeout=5).text.strip().splitlines()

    ipv4_nets = [ipaddress.ip_network(cidr) for cidr in ipv4_text]
    ipv6_nets = [ipaddress.ip_network(cidr) for cidr in ipv6_text]

    return ipv4_nets, ipv6_nets
