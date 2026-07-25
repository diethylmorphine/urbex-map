-- URBEX GRID schema — paste into Supabase → SQL Editor → Run (one time).

create table if not exists users (
    tg_id      bigint primary key,
    username   text,
    first_name text,
    points     int not null default 0,
    is_admin   boolean not null default false,
    created_at timestamptz default now()
);

create table if not exists locations (
    id          serial primary key,
    title       text not null,
    description text default '',
    lat         double precision not null,
    lng         double precision not null,
    category    text default 'other',
    tier        int not null default 0,
    status      text not null default 'pending',  -- pending | approved | rejected
    author_id   bigint not null references users(tg_id),
    created_at  timestamptz default now(),
    verified_by bigint,
    verified_at timestamptz
);

-- FKs are required for PostgREST relation embedding (counts, author join)
create table if not exists location_likes (
    user_id     bigint not null references users(tg_id),
    location_id int    not null references locations(id) on delete cascade,
    unique(user_id, location_id)
);

create table if not exists reviews (
    id          serial primary key,
    location_id int    not null references locations(id) on delete cascade,
    author_id   bigint not null references users(tg_id),
    text        text not null,
    created_at  timestamptz default now()
);

create table if not exists review_likes (
    user_id   bigint not null references users(tg_id),
    review_id int    not null references reviews(id) on delete cascade,
    unique(user_id, review_id)
);

-- atomic points increment (called via /rest/v1/rpc/add_points)
create or replace function add_points(uid bigint, amount int)
returns void language sql as $$
    update users set points = points + amount where tg_id = uid;
$$;

-- The backend uses the service key, which bypasses RLS. Lock the tables down
-- for anon/authenticated clients anyway:
alter table users          enable row level security;
alter table locations      enable row level security;
alter table location_likes enable row level security;
alter table reviews        enable row level security;
alter table review_likes   enable row level security;
