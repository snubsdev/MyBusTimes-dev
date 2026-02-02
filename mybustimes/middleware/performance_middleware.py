"""
Performance Profiling Middleware
Add this to your MIDDLEWARE setting to identify slow operations
"""
import time
import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class PerformanceLoggingMiddleware(MiddlewareMixin):
    """Log timing information for each request to identify bottlenecks."""
    
    def process_request(self, request):
        request._start_time = time.time()
        logger.info(f"[PERF] START: {request.method} {request.path}")
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        if hasattr(request, '_start_time'):
            elapsed = time.time() - request._start_time
            view_name = f"{view_func.__module__}.{view_func.__name__}"
            logger.info(f"[PERF] VIEW_START: {view_name} (after {elapsed:.3f}s)")
    
    def process_template_response(self, request, response):
        if hasattr(request, '_start_time'):
            elapsed = time.time() - request._start_time
            logger.info(f"[PERF] TEMPLATE_RENDERED (after {elapsed:.3f}s)")
        return response
    
    def process_response(self, request, response):
        if hasattr(request, '_start_time'):
            total_time = time.time() - request._start_time
            logger.info(f"[PERF] END: {request.method} {request.path} - {response.status_code} ({total_time:.3f}s)")
            
            # Flag slow requests
            if total_time > 1.0:
                logger.warning(f"[PERF] SLOW REQUEST: {request.path} took {total_time:.3f}s")
        
        return response


class DatabaseQueryLoggingMiddleware(MiddlewareMixin):
    """Log database query counts to identify N+1 problems."""
    
    def process_request(self, request):
        from django.db import connection
        request._queries_before = len(connection.queries)
    
    def process_response(self, request, response):
        from django.db import connection
        
        if hasattr(request, '_queries_before'):
            queries_count = len(connection.queries) - request._queries_before
            
            if queries_count > 0:
                total_time = sum(float(q['time']) for q in connection.queries[request._queries_before:])
                logger.info(f"[DB] {request.path}: {queries_count} queries in {total_time:.3f}s")
                
                # Flag high query counts (N+1 problem indicator)
                if queries_count > 20:
                    logger.warning(f"[DB] HIGH QUERY COUNT: {request.path} made {queries_count} queries")
                
                # Flag slow queries
                slow_queries = [q for q in connection.queries[request._queries_before:] if float(q['time']) > 0.1]
                if slow_queries:
                    logger.warning(f"[DB] SLOW QUERIES: {len(slow_queries)} queries took >0.1s")
                    for q in slow_queries[:5]:  # Show first 5 slow queries
                        logger.warning(f"[DB]   {q['time']}s: {q['sql'][:200]}")
        
        return response