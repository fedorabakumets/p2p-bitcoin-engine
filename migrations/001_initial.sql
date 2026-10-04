-- Schema v1. BTC ledger only. Ruble markup never becomes a platform balance.
-- Electrum and payment processors are not part of this migration.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_status AS ENUM ('active', 'blocked');
CREATE TYPE admin_role AS ENUM ('owner', 'operator');
CREATE TYPE trader_status AS ENUM ('pending', 'active', 'suspended');
CREATE TYPE payment_kind AS ENUM ('sbp');
CREATE TYPE execution_channel AS ENUM ('trader', 'processor');
CREATE TYPE order_status AS ENUM (
    'CREATED',
    'QUOTED',
    'SEARCHING_EXECUTOR',
    'EXECUTOR_ASSIGNED',
    'WAITING_PAYMENT',
    'CLIENT_MARKED_PAID',
    'PAYMENT_CONFIRMED',
    'RELEASING',
    'COMPLETED',
    'CANCELLED',
    'EXPIRED',
    'DISPUTED',
    'FAILED'
);
CREATE TYPE actor_type AS ENUM ('client', 'trader', 'system', 'admin');
CREATE TYPE ledger_account_kind AS ENUM (
    'trader_available',
    'trader_locked',
    'platform_revenue',
    'referral_payable',
    'external_in',
    'external_out'
);
CREATE TYPE ledger_entry_type AS ENUM (
    'DEPOSIT',
    'WITHDRAWAL',
    'ESCROW_LOCK',
    'ESCROW_UNLOCK',
    'ESCROW_RELEASE',
    'PLATFORM_REVENUE',
    'REFERRAL_REWARD',
    'ADMIN_ADJUSTMENT'
);
CREATE TYPE escrow_status AS ENUM ('locked', 'released', 'unlocked');
CREATE TYPE referral_reward_status AS ENUM ('accrued', 'paid');
CREATE TYPE address_purpose AS ENUM ('deposit', 'hot');
CREATE TYPE chain_direction AS ENUM ('in', 'out');
CREATE TYPE chain_tx_status AS ENUM (
    'seen',
    'confirmed',
    'credited',
    'broadcast',
    'confirmed_out',
    'failed'
);
CREATE TYPE dispute_status AS ENUM ('open', 'resolved');
CREATE TYPE dispute_resolution AS ENUM ('release', 'unlock');
CREATE TYPE evidence_kind AS ENUM ('screenshot', 'text');
CREATE TYPE notification_status AS ENUM ('pending', 'sent', 'failed');

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id bigint NOT NULL UNIQUE,
    username text,
    display_name text,
    referral_code text NOT NULL UNIQUE,
    referred_by_user_id uuid REFERENCES users (id),
    status user_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_no_self_referral CHECK (referred_by_user_id IS DISTINCT FROM id)
);

CREATE TABLE admin_users (
    user_id uuid PRIMARY KEY REFERENCES users (id),
    role admin_role NOT NULL
);

CREATE TABLE traders (
    user_id uuid PRIMARY KEY REFERENCES users (id),
    status trader_status NOT NULL DEFAULT 'pending',
    is_online boolean NOT NULL DEFAULT false,
    tier text NOT NULL DEFAULT 'basic',
    min_order_rub_kop bigint NOT NULL DEFAULT 0 CHECK (min_order_rub_kop >= 0),
    max_order_rub_kop bigint NOT NULL DEFAULT 10000000000 CHECK (max_order_rub_kop >= min_order_rub_kop),
    daily_limit_rub_kop bigint NOT NULL DEFAULT 10000000000 CHECK (daily_limit_rub_kop >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE trader_payment_methods (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trader_id uuid NOT NULL REFERENCES traders (user_id),
    kind payment_kind NOT NULL DEFAULT 'sbp',
    phone text NOT NULL,
    bank_name text NOT NULL,
    holder_name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX trader_one_active_sbp
    ON trader_payment_methods (trader_id)
    WHERE is_active AND kind = 'sbp';

CREATE TABLE trader_daily_volume (
    trader_id uuid NOT NULL REFERENCES traders (user_id),
    day date NOT NULL,
    used_rub_kop bigint NOT NULL DEFAULT 0 CHECK (used_rub_kop >= 0),
    PRIMARY KEY (trader_id, day)
);

CREATE TABLE settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quotes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id),
    principal_rub_kop bigint NOT NULL CHECK (principal_rub_kop > 0),
    payment_rub_kop bigint NOT NULL CHECK (payment_rub_kop >= principal_rub_kop),
    markup_bps integer NOT NULL CHECK (markup_bps >= 0),
    platform_fee_bps integer NOT NULL CHECK (platform_fee_bps >= 0),
    referral_bps integer NOT NULL CHECK (referral_bps >= 0),
    market_rate_rub_per_btc numeric(20, 8) NOT NULL CHECK (market_rate_rub_per_btc > 0),
    client_btc_sats bigint NOT NULL CHECK (client_btc_sats > 0),
    platform_fee_sats bigint NOT NULL CHECK (platform_fee_sats >= 0),
    referral_sats bigint NOT NULL CHECK (referral_sats >= 0 AND referral_sats <= platform_fee_sats),
    trader_lock_sats bigint NOT NULL CHECK (trader_lock_sats = client_btc_sats + platform_fee_sats),
    expires_at timestamptz NOT NULL,
    order_id uuid UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    client_id uuid NOT NULL REFERENCES users (id),
    quote_id uuid NOT NULL UNIQUE REFERENCES quotes (id),
    trader_id uuid REFERENCES traders (user_id),
    payment_method_id uuid REFERENCES trader_payment_methods (id),
    execution_channel execution_channel NOT NULL DEFAULT 'trader',
    status order_status NOT NULL DEFAULT 'CREATED',
    btc_address text NOT NULL,
    principal_rub_kop bigint NOT NULL CHECK (principal_rub_kop > 0),
    payment_rub_kop bigint NOT NULL CHECK (payment_rub_kop >= principal_rub_kop),
    markup_bps integer NOT NULL CHECK (markup_bps >= 0),
    platform_fee_bps integer NOT NULL CHECK (platform_fee_bps >= 0),
    market_rate_rub_per_btc numeric(20, 8) NOT NULL CHECK (market_rate_rub_per_btc > 0),
    client_btc_sats bigint NOT NULL CHECK (client_btc_sats > 0),
    platform_fee_sats bigint NOT NULL CHECK (platform_fee_sats >= 0),
    referral_sats bigint NOT NULL CHECK (referral_sats >= 0 AND referral_sats <= platform_fee_sats),
    trader_lock_sats bigint NOT NULL CHECK (trader_lock_sats = client_btc_sats + platform_fee_sats),
    quote_expires_at timestamptz NOT NULL,
    accept_expires_at timestamptz,
    pay_expires_at timestamptz,
    client_marked_paid_at timestamptz,
    trader_confirmed_at timestamptz,
    completed_at timestamptz,
    cancel_reason text,
    payout_wallet_tx_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX orders_searching_idx
    ON orders (id)
    WHERE status = 'SEARCHING_EXECUTOR';

ALTER TABLE quotes
    ADD CONSTRAINT quotes_order_fk FOREIGN KEY (order_id) REFERENCES orders (id);

CREATE TABLE order_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id uuid NOT NULL REFERENCES orders (id),
    from_status order_status,
    to_status order_status NOT NULL,
    actor_type actor_type NOT NULL,
    actor_user_id uuid REFERENCES users (id),
    idempotency_key text NOT NULL UNIQUE,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX order_events_order_id_idx ON order_events (order_id, id);

CREATE TABLE ledger_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    kind ledger_account_kind NOT NULL,
    user_id uuid REFERENCES users (id),
    asset text NOT NULL DEFAULT 'btc' CHECK (asset = 'btc'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id uuid NOT NULL,
    account_id uuid NOT NULL REFERENCES ledger_accounts (id),
    order_id uuid REFERENCES orders (id),
    amount_sats bigint NOT NULL CHECK (amount_sats <> 0),
    entry_type ledger_entry_type NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ledger_entries_group_idx ON ledger_entries (group_id);
CREATE INDEX ledger_entries_order_idx ON ledger_entries (order_id);

CREATE TABLE ledger_balances (
    account_id uuid PRIMARY KEY REFERENCES ledger_accounts (id),
    balance_sats bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION ledger_balances_non_negative() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    account_kind ledger_account_kind;
BEGIN
    SELECT kind INTO account_kind FROM ledger_accounts WHERE id = NEW.account_id;
    IF account_kind IN (
        'trader_available',
        'trader_locked',
        'platform_revenue',
        'referral_payable'
    ) AND NEW.balance_sats < 0 THEN
        RAISE EXCEPTION 'negative balance on %', account_kind;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_balances_non_negative
    BEFORE INSERT OR UPDATE ON ledger_balances
    FOR EACH ROW
    EXECUTE FUNCTION ledger_balances_non_negative();

CREATE TABLE escrow_locks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES orders (id),
    trader_id uuid NOT NULL REFERENCES traders (user_id),
    amount_sats bigint NOT NULL CHECK (amount_sats > 0),
    status escrow_status NOT NULL DEFAULT 'locked',
    lock_group_id uuid NOT NULL,
    release_group_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);

CREATE TABLE referral_rewards (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES orders (id),
    referrer_user_id uuid NOT NULL REFERENCES users (id),
    referred_user_id uuid NOT NULL REFERENCES users (id),
    amount_sats bigint NOT NULL CHECK (amount_sats >= 0),
    ledger_group_id uuid NOT NULL,
    status referral_reward_status NOT NULL DEFAULT 'accrued',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE wallet_addresses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trader_id uuid REFERENCES traders (user_id),
    purpose address_purpose NOT NULL,
    address text NOT NULL UNIQUE,
    derivation_index integer,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deposit_address_has_trader CHECK (
        (purpose = 'deposit' AND trader_id IS NOT NULL)
        OR (purpose = 'hot' AND trader_id IS NULL)
    )
);

CREATE TABLE wallet_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    txid text NOT NULL,
    vout integer NOT NULL CHECK (vout >= 0),
    direction chain_direction NOT NULL,
    address_id uuid NOT NULL REFERENCES wallet_addresses (id),
    amount_sats bigint NOT NULL CHECK (amount_sats > 0),
    confirmations integer NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
    status chain_tx_status NOT NULL,
    order_id uuid REFERENCES orders (id),
    ledger_group_id uuid UNIQUE,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (txid, vout, direction)
);

ALTER TABLE orders
    ADD CONSTRAINT orders_payout_wallet_tx_fk
    FOREIGN KEY (payout_wallet_tx_id) REFERENCES wallet_transactions (id);

CREATE TABLE disputes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES orders (id),
    opened_by uuid NOT NULL REFERENCES users (id),
    reason text NOT NULL,
    status dispute_status NOT NULL DEFAULT 'open',
    resolution dispute_resolution,
    resolved_by uuid REFERENCES users (id),
    resolution_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT dispute_resolution_pair CHECK (
        (status = 'open' AND resolution IS NULL AND resolved_at IS NULL)
        OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)
    )
);

CREATE TABLE dispute_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id uuid NOT NULL REFERENCES disputes (id),
    uploaded_by uuid NOT NULL REFERENCES users (id),
    telegram_file_id text NOT NULL,
    kind evidence_kind NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id),
    order_id uuid REFERENCES orders (id),
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status notification_status NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz
);

CREATE INDEX notifications_pending_idx
    ON notifications (created_at)
    WHERE status = 'pending';

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id uuid REFERENCES users (id),
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid,
    before_state jsonb,
    after_state jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_keys (
    key text PRIMARY KEY,
    scope text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO settings (key, value) VALUES
    ('quote_ttl_seconds', '120'),
    ('accept_ttl_seconds', '20'),
    ('pay_ttl_seconds', '900'),
    ('default_markup_bps', '1800'),
    ('platform_fee_bps', '0'),
    ('referral_bps', '0');

COMMIT;
