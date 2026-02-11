-- Token bucket acquire for per-function rate limiting
-- KEYS[1] = bucket key
-- ARGV[1] = now_ms
-- ARGV[2] = capacity
-- ARGV[3] = refill_per_ms
-- ARGV[4] = ttl_ms
--
-- Returns: 1 if token acquired, 0 if limited

local bucket_key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_per_ms = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])

local state = redis.call("HMGET", bucket_key, "tokens", "ts")
local tokens = tonumber(state[1])
local ts = tonumber(state[2])

if not tokens then
    tokens = capacity
end
if not ts then
    ts = now_ms
end

if now_ms > ts then
    local elapsed = now_ms - ts
    tokens = math.min(capacity, tokens + (elapsed * refill_per_ms))
    ts = now_ms
end

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call("HSET", bucket_key, "tokens", tokens, "ts", ts)
redis.call("PEXPIRE", bucket_key, ttl_ms)

return allowed
