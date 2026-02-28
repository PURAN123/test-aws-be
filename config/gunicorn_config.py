import multiprocessing

# Gunicorn configuration for production
bind = 'unix:/var/www/test-aws-be/test-aws-be/gunicorn.sock'
workers = max(2, multiprocessing.cpu_count() * 2 + 1)
worker_class = 'sync'
threads = 2
timeout = 30
keepalive = 2
accesslog = '-'  # stdout
errorlog = '-'   # stderr
# Graceful timeout for worker shutdown
graceful_timeout = 30
