-- Enemy picks the legal move that maximizes % HP damage to your Mon (trainer_atk_pct_max decides).
-- strikes_first ≈ outspeed OR (your move is EFFECT_PRIORITY_HIT / EFFECT_SUCKER_PUNCH AND theirs is not);
-- slower + both priority is treated as foe first (tie assumes worst when equal Spe and both prio).
WITH trainer_mon AS (
	SELECT p.id AS tid, p.spe AS trainer_spe FROM pokemon p
	WHERE p.species_code = 'RATICATE' AND p.form_code = 'ALOLAN'
),
counter_level AS (
	SELECT DISTINCT p.id AS counter_id, s.lvl_cap, tr.tid, tr.trainer_spe
	FROM splits s
	INNER JOIN pokemon_split ps ON (ps.splits_id <= s.id AND ps.splits_id IS NOT NULL)
	INNER JOIN pokemon p ON (p.species_code = ps.species_code AND p.form_code = ps.form_code)
	CROSS JOIN trainer_mon tr
	WHERE s.id = 3
	#AND p.species_code IN ('STEELIX', 'SCYTHE')
),
enemy_move_roll AS (
	SELECT
		cl.counter_id, cl.lvl_cap, mv.id AS enemy_move_id, mv.code AS enemy_pick_move,
		mv.effect AS trainer_move_effect,
		calculate_attack_damage_percent(cl.tid, mv.id, cl.counter_id, cl.lvl_cap, cl.lvl_cap, 'max') AS trainer_atk_pct_max,
		calculate_attack_damage_percent(cl.tid, mv.id, cl.counter_id, cl.lvl_cap, cl.lvl_cap, 'min') AS trainer_atk_pct_min
	FROM counter_level cl
	CROSS JOIN moves mv
	WHERE mv.`code` IN ('HYPER_FANG', 'BITE', 'PURSUIT', 'SUCKER_PUNCH')
),
enemy_optimal AS (
	SELECT counter_id, lvl_cap, enemy_move_id, enemy_pick_move,
		trainer_move_effect,
		trainer_atk_pct_max, trainer_atk_pct_min
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
	SELECT ps.species_code, ps.form_code,
		m.`code`, m.effect AS counter_move_effect, m.accuracy,
		p.spe AS counter_spe, tr.trainer_spe,
		eo.enemy_pick_move, eo.trainer_move_effect,
		calculate_attack_damage_percent(p.id, m.id, tr.tid, s.lvl_cap, s.lvl_cap, 'min') AS dam_perc_min,
		calculate_attack_damage_percent(p.id, m.id, tr.tid, s.lvl_cap, s.lvl_cap, 'max') AS dam_perc_max,
		eo.trainer_atk_pct_min AS dam_perc_min_atc, eo.trainer_atk_pct_max AS dam_perc_max_atc
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
		AND NOT (p.species_code IN ('GYARADOS', 'SLOWKING', 'WIGGLYTUFF', 'SCIZOR', 'NIDOQUEEN', 'CLEFABLE')
			AND pm.learn_method = 'level_up' AND pm.learn_level = 1 AND s.id < 5)
		AND NOT (p.species_code IN ('HERACROSS') AND m.`code` = 'NIGHT_SLASH' AND s.id < 5)
),
scored AS (
	SELECT raw_moves.*,
		CASE WHEN COALESCE(dam_perc_min, 0) <= 0 THEN 9999 ELSE CEIL(100 / NULLIF(dam_perc_min, 0)) END AS turns_to_ko_enemy,
		CASE WHEN COALESCE(dam_perc_max_atc, 0) <= 0 THEN 9999 ELSE CEIL(100 / NULLIF(dam_perc_max_atc, 0)) END AS turns_to_survive_enemy,
		CASE WHEN counter_spe > trainer_spe THEN 1 ELSE 0 END AS outspeed_trainer,
		CASE WHEN counter_move_effect IN ('EFFECT_PRIORITY_HIT', 'EFFECT_SUCKER_PUNCH') THEN 1 ELSE 0 END AS counter_moves_first_priority,
		CASE WHEN trainer_move_effect IN ('EFFECT_PRIORITY_HIT', 'EFFECT_SUCKER_PUNCH') THEN 1 ELSE 0 END AS trainer_moves_first_priority,
		CASE
			WHEN counter_spe > trainer_spe THEN 1
			WHEN counter_move_effect IN ('EFFECT_PRIORITY_HIT', 'EFFECT_SUCKER_PUNCH')
				AND trainer_move_effect NOT IN ('EFFECT_PRIORITY_HIT', 'EFFECT_SUCKER_PUNCH') THEN 1
			ELSE 0
		END AS strikes_first
	FROM raw_moves
),
ranked AS (
	SELECT scored.*,
		(turns_to_survive_enemy - turns_to_ko_enemy + strikes_first) AS race_favor,
		ROW_NUMBER() OVER (
			PARTITION BY scored.species_code, scored.form_code
			ORDER BY turns_to_ko_enemy ASC, turns_to_survive_enemy DESC, strikes_first DESC,
				counter_moves_first_priority DESC, dam_perc_min DESC, dam_perc_max_atc DESC,
				counter_spe DESC, scored.`code`
		) AS rn
	FROM scored
)
SELECT * FROM ranked
WHERE rn = 1
ORDER BY
	CASE 
		WHEN (turns_to_ko_enemy IN (1) AND outspeed_trainer = 1) THEN 2 
		#WHEN (turns_to_ko_enemy IN (2) AND outspeed_trainer = 1) THEN 1 
	ELSE 0 END DESC,
	race_favor DESC, turns_to_ko_enemy ASC,
	turns_to_survive_enemy + strikes_first DESC,
	strikes_first DESC, outspeed_trainer DESC, dam_perc_min DESC, dam_perc_max_atc ASC, counter_spe DESC, species_code;
