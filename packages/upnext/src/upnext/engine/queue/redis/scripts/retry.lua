-- Atomic job retry
-- KEYS[1] = stream_key (for XACK)
-- KEYS[2] = job_key (job data storage)
-- KEYS[3] = dest_key (stream or scheduled ZSET)
-- KEYS[4] = job_index_key (job ID -> job key mapping)
-- ARGV[1] = consumer_group
-- ARGV[2] = message_id (can be empty)
-- ARGV[3] = job_data (JSON)
-- ARGV[4] = job_ttl_seconds
-- ARGV[5] = job_id
-- ARGV[6] = function_name
-- ARGV[7] = delay (0 for immediate, >0 for delayed)
-- ARGV[8] = stream_maxlen
--
-- Returns: "OK" on success

local stream_key = KEYS[1]
local job_key = KEYS[2]
local dest_key = KEYS[3]
local job_index_key = KEYS[4]

local consumer_group = ARGV[1]
local message_id = ARGV[2]
local job_data = ARGV[3]
local job_ttl = tonumber(ARGV[4])
local job_id = ARGV[5]
local function_name = ARGV[6]
local delay = tonumber(ARGV[7])
local stream_maxlen = tonumber(ARGV[8])

-- ACK the current message if we have a message_id
if message_id and message_id ~= "" then
    redis.call("XACK", stream_key, consumer_group, message_id)
end

-- Store updated job data with TTL
redis.call("SETEX", job_key, job_ttl, job_data)
redis.call("SETEX", job_index_key, job_ttl, job_key)

-- Add to destination (stream for immediate, ZSET for scheduled)
if delay > 0 then
    -- Delayed retry - add to sorted set with future timestamp
    local scheduled_time = redis.call("TIME")
    local now = tonumber(scheduled_time[1]) + tonumber(scheduled_time[2]) / 1000000
    redis.call("ZADD", dest_key, now + delay, job_id)
else
    -- Immediate retry - add to stream
    redis.call("XADD", dest_key, "MAXLEN", "~", stream_maxlen, "*",
               "job_id", job_id, "function", function_name, "data", job_data)
end

return "OK"
