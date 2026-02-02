"""
Quick Django Performance Diagnosis Script - Windows Compatible
Run this to immediately identify performance issues

Usage:
    python manage.py shell < quick_diagnosis_windows.py
"""

import time
from django.core.cache import cache
from django.db import connection, reset_queries
from django.test import RequestFactory
from django.contrib.auth import get_user_model

print("=" * 80)
print("DJANGO PERFORMANCE QUICK DIAGNOSIS")
print("=" * 80)

User = get_user_model()

# Test 1: Cache Performance
print("\n[TEST 1] Cache Performance")
print("-" * 40)
try:
    start = time.time()
    cache.set('test_key', 'test_value', 1)
    result = cache.get('test_key')
    elapsed = time.time() - start
    
    if elapsed > 0.1:
        print("[WARNING] SLOW CACHE: %.3fs (should be <0.01s)" % elapsed)
        print("  -> Check your cache backend (Redis/Memcached connection)")
    else:
        print("[OK] Cache: %.3fs" % elapsed)
except Exception as e:
    print("[ERROR] CACHE ERROR: %s" % e)
    print("  -> Cache backend may be misconfigured")

# Test 2: Database Connection
print("\n[TEST 2] Database Performance")
print("-" * 40)
try:
    reset_queries()
    start = time.time()
    user_count = User.objects.count()
    elapsed = time.time() - start
    query_count = len(connection.queries)
    
    print("  Users in DB: %d" % user_count)
    print("  Query time: %.3fs" % elapsed)
    print("  Queries executed: %d" % query_count)
    
    if elapsed > 0.1:
        print("[WARNING] SLOW DATABASE: Simple count took %.3fs" % elapsed)
    else:
        print("[OK] Database performance good")
except Exception as e:
    print("[ERROR] DATABASE ERROR: %s" % e)

# Test 3: Context Processor Performance
print("\n[TEST 3] Context Processor Performance")
print("-" * 40)
try:
    # Import your context processor
    from main.context_processors import theme_settings
    
    # Create fake request
    factory = RequestFactory()
    request = factory.get('/test/')
    
    # Add user
    try:
        request.user = User.objects.first()
    except:
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
    
    # Add required attributes
    request.COOKIES = {}
    request.META = {
        'REMOTE_ADDR': '127.0.0.1',
        'HTTP_USER_AGENT': 'TestAgent/1.0',
    }
    
    # Time it
    reset_queries()
    start = time.time()
    result = theme_settings(request)
    elapsed = time.time() - start
    query_count = len(connection.queries)
    
    print("  Execution time: %.3fs" % elapsed)
    print("  Database queries: %d" % query_count)
    print("  Context variables: %d" % len(result))
    
    if elapsed > 0.5:
        print("[WARNING] SLOW CONTEXT PROCESSOR: %.3fs" % elapsed)
        print("  -> Review theme_settings() for optimization")
    elif query_count > 20:
        print("[WARNING] TOO MANY QUERIES: %d queries" % query_count)
        print("  -> Possible N+1 query problem")
    else:
        print("[OK] Context processor performance good")
    
    # Show queries if there are any slow ones
    if query_count > 0 and elapsed > 0.1:
        print("\n  Recent queries:")
        for q in connection.queries[-5:]:
            print("    %.3fs: %s..." % (float(q['time']), q['sql'][:100]))
            
except ImportError:
    print("[WARNING] Could not import theme_settings")
    print("  -> Adjust the import path in this script")
except Exception as e:
    print("[ERROR] CONTEXT PROCESSOR ERROR: %s" % e)
    import traceback
    traceback.print_exc()

# Test 4: Model Query Performance
print("\n[TEST 4] Common Query Patterns")
print("-" * 40)
try:
    from main.models import Device
    
    # Test 1: Simple filter
    reset_queries()
    start = time.time()
    devices = list(Device.objects.all()[:10])
    elapsed = time.time() - start
    query_count = len(connection.queries)
    
    print("  Device query: %.3fs (%d queries)" % (elapsed, query_count))
    
    # Test 2: Filter with FK access (N+1 detector)
    if devices:
        reset_queries()
        start = time.time()
        for d in devices:
            try:
                _ = d.last_user  # Access FK field
            except:
                pass
        elapsed = time.time() - start
        query_count = len(connection.queries)
        
        if query_count > 1:
            print("[WARNING] N+1 DETECTED: %d queries for %d devices" % (query_count, len(devices)))
            print("  -> Use select_related('last_user')")
        else:
            print("[OK] No N+1 problem detected")
    
except ImportError:
    print("[WARNING] Could not import models")
except Exception as e:
    print("[ERROR] MODEL TEST ERROR: %s" % e)

# Test 5: Check for Missing Indexes
print("\n[TEST 5] Database Indexes")
print("-" * 40)
try:
    from main.models import Device
    
    # Check if fingerprint has index
    fingerprint_field = Device._meta.get_field('fingerprint')
    has_index = fingerprint_field.db_index
    
    if not has_index:
        print("[WARNING] MISSING INDEX: Device.fingerprint should have db_index=True")
    else:
        print("[OK] Device.fingerprint is indexed")
    
    # Check last_ip
    try:
        last_ip_field = Device._meta.get_field('last_ip')
        has_index = last_ip_field.db_index
        
        if not has_index:
            print("[WARNING] MISSING INDEX: Device.last_ip should have db_index=True")
        else:
            print("[OK] Device.last_ip is indexed")
    except:
        pass
        
except Exception as e:
    print("[ERROR] INDEX CHECK ERROR: %s" % e)

# Summary
print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
print("\nNext steps:")
print("1. Review any [WARNING] items above")
print("2. Add PerformanceLoggingMiddleware to see real request timings")
print("3. Install django-debug-toolbar for detailed profiling")
print("4. Check DEBUGGING_GUIDE.md for specific solutions")
print("=" * 80)