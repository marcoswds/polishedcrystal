-- Enemy picks the legal move that maximizes % HP damage to your Mon (trainer_atk_pct_max decides).
-- That row also carries trainer_atk_pct_min / Max for THAT move only. Counter KO uses dam_perc_min vs trainer.
WITH trainer_mon AS (
	SELECT p.id AS tid, p.spe AS trainer_spe FROM pokemon p
	WHERE p.species_code = 'TOGETIC' AND p.form_code = 'PLAIN'
),
counter_level AS (
	SELECT DISTINCT p.id AS counter_id, s.lvl_cap, tr.tid, tr.trainer_spe
	FROM splits s
	INNER JOIN pokemon_split ps ON (ps.splits_id <= s.id AND ps.splits_id IS NOT NULL)
	INNER JOIN pokemon p ON (p.species_code = ps.species_code AND p.form_code = ps.form_code)
	CROSS JOIN trainer_mon tr
	WHERE s.id = 3
),
enemy_move_roll AS (
	SELECT
		cl.counter_id, cl.lvl_cap, mv.id AS enemy_move_id, mv.code AS enemy_pick_move,
		calculate_attack_damage_percent(cl.tid, mv.id, cl.counter_id, cl.lvl_cap, cl.lvl_cap, 'max') AS trainer_atk_pct_max,
		calculate_attack_damage_percent(cl.tid, mv.id, cl.counter_id, cl.lvl_cap, cl.lvl_cap, 'min') AS trainer_atk_pct_min
	FROM counter_level cl
	CROSS JOIN moves mv
	WHERE mv.`code` IN ('HEADBUTT', 'METRONOME', 'SWEET_KISS', 'DISARM_VOICE')
),
enemy_optimal AS (
	SELECT counter_id, lvl_cap, enemy_move_id, enemy_pick_move, trainer_atk_pct_max, trainer_atk_pct_min
	FROM (
		SELECT *,
			ROW_NUMBER() OVER (
				PARTITION BY counter_id, lvl_cap
				ORDER BY trainer_atk_pct_max DESC, enemy_pick_move ASC
			) AS pick_rn
		FROM enemy_move_roll
	) picks
	WHERE pick_rn = 1
),
raw_moves AS (
	SELECT ps.species_code, ps.form_code, m.`code`, m.accuracy,
		p.id AS counter_id, p.spe AS counter_spe, tr.trainer_spe, tr.tid, s.lvl_cap AS lvl_cap,
		eo.enemy_pick_move, eo.trainer_atk_pct_min AS dam_perc_min_atc, eo.trainer_atk_pct_max AS dam_perc_max_atc,
		calculate_attack_damage_percent(p.id, m.id, tr.tid, s.lvl_cap, s.lvl_cap, 'min') AS dam_perc_min,
		calculate_attack_damage_percent(p.id, m.id, tr.tid, s.lvl_cap, s.lvl_cap, 'max') AS dam_perc_max
	FROM splits s
	INNER JOIN pokemon_split ps ON (ps.splits_id <= s.id AND ps.splits_id IS NOT NULL)
	INNER JOIN pokemon p ON (p.species_code = ps.species_code AND p.form_code = ps.form_code)
	INNER JOIN pokemon_moves pm ON (p.id = pm.pokemon_id AND pm.learn_level <= s.lvl_cap)
	INNER JOIN moves m ON (pm.move_id = m.id)
	LEFT JOIN moves_split ms ON (m.`code` = ms.move_code AND ms.splits_id <= s.id)
	INNER JOIN trainer_mon tr
	INNER JOIN enemy_optimal eo ON (eo.counter_id = p.id AND eo.lvl_cap = s.lvl_cap)
	WHERE s.id = 3
		AND (pm.learn_method IN ('level_up', 'prev_evo_lvl_up') OR ms.move_code IS NOT NULL)
		AND m.`code` NOT IN ('FUTURE_SIGHT', 'DREAM_EATER', 'BLIZZARD', 'THUNDER', 'FIRE_BLAST', 'SUCKER_PUNCH')
		AND NOT (p.species_code IN ('GYARADOS', 'SLOWKING', 'WIGGLYTUFF')
			AND pm.learn_method = 'level_up' AND pm.learn_level = 1)
		AND NOT (p.species_code IN ('HERACROSS') AND m.`code` = 'NIGHT_SLASH' AND s.id < 5)
),
scored AS (
	SELECT raw_moves.*,
		CASE WHEN COALESCE(dam_perc_min, 0) <= 0 THEN 9999 ELSE CEIL(100 / NULLIF(dam_perc_min, 0)) END AS turns_to_ko_enemy,
		CASE WHEN COALESCE(dam_perc_max_atc, 0) <= 0 THEN 9999 ELSE CEIL(100 / NULLIF(dam_perc_max_atc, 0)) END AS turns_to_survive_enemy,
		CASE WHEN counter_spe > trainer_spe THEN 1 ELSE 0 END AS outspeed_trainer
	FROM raw_moves
),
ranked AS (
	SELECT scored.*,
		(turns_to_survive_enemy - turns_to_ko_enemy + outspeed_trainer) AS race_favor,
		ROW_NUMBER() OVER (
			PARTITION BY scored.species_code, scored.form_code
			ORDER BY turns_to_ko_enemy ASC, turns_to_survive_enemy DESC, outspeed_trainer DESC,
				dam_perc_min DESC, dam_perc_max_atc DESC, counter_spe DESC, scored.`code`
		) AS rn
	FROM scored
)
SELECT * FROM ranked WHERE rn = 1
ORDER BY turns_to_ko_enemy ASC, turns_to_survive_enemy DESC, race_favor DESC,
	outspeed_trainer DESC, counter_spe DESC, species_code;