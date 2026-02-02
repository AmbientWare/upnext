"""
Conduit Examples.

- service.py: Full-featured e-commerce service with APIs, tasks, crons, and events
- load_generator.py: Load testing tool for generating realistic traffic

Run the service:
    conduit dev examples/service.py

Run the load generator:
    python -m examples.load_generator --mode demo
    python -m examples.load_generator --mode continuous --rate 10 --duration 300
    python -m examples.load_generator --mode burst --burst 100
"""
