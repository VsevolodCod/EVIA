CREATE SCHEMA private;
CREATE TABLE public.orders (id integer PRIMARY KEY, amount integer NOT NULL);
INSERT INTO public.orders (id, amount) SELECT value, 10 FROM generate_series(1, 500) AS value;
CREATE TABLE private.payroll (id integer PRIMARY KEY, salary integer NOT NULL);
INSERT INTO private.payroll VALUES (1, 100000);
CREATE ROLE evia_reader LOGIN PASSWORD 'evia_test_only';
GRANT CONNECT ON DATABASE evia_test TO evia_reader;
GRANT USAGE ON SCHEMA public TO evia_reader;
GRANT SELECT ON public.orders TO evia_reader;
