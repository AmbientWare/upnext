-- Atomic enqueue with deduplication check
-- KEYS[1] = dedup_key (SET for dedup tracking)
-- KEYS[2] = job_key (job data storage)
-- KEYS[3] = stream_key or scheduled_key (destination)
-- KEYS[4] = job_index_key (job ID -> job key mapping)
-- ARGV[1] = dedup_value (job.key for dedup)
-- ARGV[2] = job_data (JSON)
-- ARGV[3] = job_ttl_seconds
-- ARGV[4] = job_id
-- ARGV[5] = function_name
-- ARGV[6] = scheduled_time (0 for immediate, >0 for delayed)
-- ARGV[7] = stream_maxlen
--
-- Returns: "OK" on success, "DUPLICATE" if duplicate found

local dedup_key = KEYS[1]
local job_key = KEYS[2]
local dest_key = KEYS[3]
local job_index_key = KEYS[4]

local dedup_value = ARGV[1]
local job_data = ARGV[2]
local job_ttl = tonumber(ARGV[3])
local job_id = ARGV[4]
local function_name = ARGV[5]
local scheduled_time = tonumber(ARGV[6])
local stream_maxlen = tonumber(ARGV[7])

-- Check for duplicate if dedup_value is provided
if dedup_value and dedup_value ~= "" then
    local is_dup = redis.call("SISMEMBER", dedup_key, dedup_value)
    if is_dup == 1 then
        return "DUPLICATE"
    end
    -- Add dedup key with TTL
    redis.call("SADD", dedup_key, dedup_value)
    redis.call("EXPIRE", dedup_key, job_ttl)
end

-- Store job data with TTL
redis.call("SETEX", job_key, job_ttl, job_data)
redis.call("SETEX", job_index_key, job_ttl, job_key)

-- Add to destination (stream for immediate, ZSET for scheduled)
if scheduled_time > 0 then
    -- Delayed job - add to sorted set
    redis.call("ZADD", dest_key, scheduled_time, job_id)
else
    -- Immediate job - add to stream with full job data
    -- This allows dequeue to skip the extra GET call
    redis.call("XADD", dest_key, "MAXLEN", "~", stream_maxlen, "*",
               "job_id", job_id, "function", function_name, "data", job_data)
end

return "OK"
