USE pokemon_db;

DROP FUNCTION IF EXISTS calculate_attack_damage_percent;

DELIMITER $$

CREATE FUNCTION calculate_attack_damage_percent(
    p_attacker_pokemon_id INT,
    p_move_id INT,
    p_defender_pokemon_id INT,
    p_attacker_level INT,
    p_defender_level INT,
    p_mode VARCHAR(8) -- 'min' or 'max'
)
RETURNS DECIMAL(10,4)
READS SQL DATA
DETERMINISTIC
BEGIN
    DECLARE v_move_power INT;
    DECLARE v_move_type_id INT;
    DECLARE v_move_category VARCHAR(10);
    DECLARE v_move_effect VARCHAR(64);
    DECLARE v_hit_count INT DEFAULT 1;

    DECLARE v_attacker_atk INT;
    DECLARE v_attacker_sat INT;
    DECLARE v_attacker_type1 INT;
    DECLARE v_attacker_type2 INT;

    DECLARE v_defender_def INT;
    DECLARE v_defender_sdf INT;
    DECLARE v_defender_hp_base INT;
    DECLARE v_defender_type1 INT;
    DECLARE v_defender_type2 INT;

    DECLARE v_attacker_iv INT;
    DECLARE v_defender_iv INT;

    DECLARE v_attacker_effective_atk INT;
    DECLARE v_attacker_effective_sat INT;
    DECLARE v_defender_effective_def INT;
    DECLARE v_defender_effective_sdf INT;
    DECLARE v_defender_effective_hp INT;

    DECLARE v_attack_stat INT;
    DECLARE v_defense_stat INT;
    DECLARE v_stab DECIMAL(6,3);
    DECLARE v_type_relation VARCHAR(32);
    DECLARE v_type_multiplier DECIMAL(6,3);
    DECLARE v_move_type_code VARCHAR(32);
    DECLARE v_def_type1_code VARCHAR(32);
    DECLARE v_def_type2_code VARCHAR(32);
    DECLARE v_attacker_level_clamped INT;
    DECLARE v_defender_level_clamped INT;
    DECLARE v_damage DECIMAL(16,6);
    DECLARE v_percent DECIMAL(16,6);
    DECLARE v_fixed_damage_hits DECIMAL(6,3);

    SELECT m.power, m.type_id, m.category, m.effect
      INTO v_move_power, v_move_type_id, v_move_category, v_move_effect
      FROM moves m
     WHERE m.id = p_move_id;

    IF v_move_category NOT IN ('PHYSICAL', 'SPECIAL') OR v_move_category IS NULL THEN
        RETURN 0.0000;
    END IF;

    SET v_hit_count = 1;

    -- Magnitude: random BP from table; min = lowest (10), max = highest (150).
    IF v_move_effect = 'EFFECT_MAGNITUDE' THEN
        IF p_mode = 'min' THEN
            SET v_move_power = 10;
        ELSE
            SET v_move_power = 150;
        END IF;
    ELSEIF v_move_effect NOT IN ('EFFECT_LEVEL_DAMAGE', 'EFFECT_SUPER_FANG')
          AND (v_move_power IS NULL OR v_move_power <= 0) THEN
        RETURN 0.0000;
    ELSEIF v_move_effect = 'EFFECT_DOUBLE_HIT' THEN
        SET v_hit_count = 2;
    ELSEIF v_move_effect = 'EFFECT_MULTI_HIT' THEN
        -- Gen-style 2–5 hits; min mode = 2 hits, max mode = 5 hits (Skill Link / best roll).
        IF p_mode = 'min' THEN
            SET v_hit_count = 2;
        ELSE
            SET v_hit_count = 5;
        END IF;
    END IF;

    SELECT p.atk, p.sat, p.primary_type_id, p.secondary_type_id
      INTO v_attacker_atk, v_attacker_sat, v_attacker_type1, v_attacker_type2
      FROM pokemon p
     WHERE p.id = p_attacker_pokemon_id;

    SELECT p.def, p.sdf, p.hp, p.primary_type_id, p.secondary_type_id
      INTO v_defender_def, v_defender_sdf, v_defender_hp_base, v_defender_type1, v_defender_type2
      FROM pokemon p
     WHERE p.id = p_defender_pokemon_id;

    IF p_mode = 'min' THEN
        -- Worst case for attacker, best case for defender.
        SET v_attacker_iv = 0;
        SET v_defender_iv = 31;
    ELSE
        -- Best case for attacker, worst case for defender.
        SET v_attacker_iv = 31;
        SET v_defender_iv = 0;
    END IF;

    -- Clamp levels to 1..100.
    SET v_attacker_level_clamped = GREATEST(1, LEAST(100, p_attacker_level));
    SET v_defender_level_clamped = GREATEST(1, LEAST(100, p_defender_level));

    -- Stat formulas with IV only (EVs ignored), neutral nature:
    -- HP: FLOOR(((2*base + IV) * level) / 100) + level + 10
    -- Others: FLOOR(((2*base + IV) * level) / 100) + 5
    SET v_attacker_effective_atk = FLOOR(((2 * v_attacker_atk + v_attacker_iv) * v_attacker_level_clamped) / 100) + 5;
    SET v_attacker_effective_sat = FLOOR(((2 * v_attacker_sat + v_attacker_iv) * v_attacker_level_clamped) / 100) + 5;
    SET v_defender_effective_def = FLOOR(((2 * v_defender_def + v_defender_iv) * v_defender_level_clamped) / 100) + 5;
    SET v_defender_effective_sdf = FLOOR(((2 * v_defender_sdf + v_defender_iv) * v_defender_level_clamped) / 100) + 5;
    SET v_defender_effective_hp = FLOOR(((2 * v_defender_hp_base + v_defender_iv) * v_defender_level_clamped) / 100) + v_defender_level_clamped + 10;

    IF v_defender_effective_hp <= 0 THEN
        RETURN 0.0000;
    END IF;

    -- Type codes for rules not represented in type_matchups.asm (e.g. GROUND vs FLYING is commented there).
    SELECT t.code INTO v_move_type_code FROM types t WHERE t.id = v_move_type_id LIMIT 1;
    SELECT t.code INTO v_def_type1_code FROM types t WHERE t.id = v_defender_type1 LIMIT 1;
    IF v_defender_type2 IS NOT NULL THEN
        SELECT t.code INTO v_def_type2_code FROM types t WHERE t.id = v_defender_type2 LIMIT 1;
    ELSE
        SET v_def_type2_code = NULL;
    END IF;

    -- Standard chart: Ground does not affect Flying (still true when dual-typed, e.g. Poison/Flying).
    IF v_move_type_code = 'GROUND' AND (v_def_type1_code = 'FLYING' OR v_def_type2_code = 'FLYING') THEN
        SET v_type_relation = 'Immune';
        SET v_type_multiplier = 0;
    ELSE
        SELECT tdr.relation
          INTO v_type_relation
          FROM type_defensive_relations tdr
         WHERE tdr.type1_id = LEAST(v_defender_type1, IFNULL(v_defender_type2, v_defender_type1))
           AND (
                (v_defender_type2 IS NULL AND tdr.type2_id IS NULL)
                OR
                (v_defender_type2 IS NOT NULL AND tdr.type2_id = GREATEST(v_defender_type1, v_defender_type2))
           )
           AND tdr.type3_id = v_move_type_id
         LIMIT 1;

        SET v_type_multiplier = CASE v_type_relation
            WHEN 'Immune' THEN 0
            WHEN '2x resist' THEN 0.25
            WHEN 'Resist' THEN 0.5
            WHEN 'Normal' THEN 1
            WHEN 'Super effective' THEN 2
            WHEN '2x super effective' THEN 4
            ELSE 1
        END;
    END IF;

    -- Night Shade / Seismic Toss / static BP: only immunity matters (0 vs not); never SE/resist on fixed damage.
    SET v_fixed_damage_hits = IF(v_type_multiplier = 0, 0, 1);

    -- Fixed / level-based damage: ignores atk/def and STAB; type chart only for immunity (e.g. Ghost Night Shade vs Normal).
    IF v_move_effect = 'EFFECT_SUPER_FANG' THEN
        IF v_type_multiplier = 0 THEN
            RETURN 0.0000;
        END IF;
        RETURN 50.0000;
    END IF;

    IF v_move_effect = 'EFFECT_LEVEL_DAMAGE' THEN
        -- Night Shade / Seismic Toss: damage equals user's level when not immune (never scaled by SE/resist).
        SET v_percent = (v_attacker_level_clamped / v_defender_effective_hp) * 100.0 * v_fixed_damage_hits;
        RETURN ROUND(v_percent, 4);
    END IF;

    IF v_move_effect = 'EFFECT_STATIC_DAMAGE' THEN
        -- Sonic Boom (20), Dragon Rage (40), etc.: fixed power unless immune.
        SET v_percent = (v_move_power / v_defender_effective_hp) * 100.0 * v_fixed_damage_hits;
        RETURN ROUND(v_percent, 4);
    END IF;

    IF v_move_category = 'PHYSICAL' THEN
        SET v_attack_stat = v_attacker_effective_atk;
        SET v_defense_stat = v_defender_effective_def;
    ELSE
        SET v_attack_stat = v_attacker_effective_sat;
        SET v_defense_stat = v_defender_effective_sdf;
    END IF;

    IF v_defense_stat <= 0 THEN
        RETURN 0.0000;
    END IF;

    IF v_move_type_id = v_attacker_type1 OR (v_attacker_type2 IS NOT NULL AND v_move_type_id = v_attacker_type2) THEN
        SET v_stab = 1.5;
    ELSE
        SET v_stab = 1.0;
    END IF;

    -- Simplified standard damage per hit (no weather/crit/random/items/abilities).
    SET v_damage =
        (FLOOR(((2 * v_attacker_level_clamped / 5 + 2) * v_move_power * v_attack_stat / v_defense_stat) / 50) + 2)
        * v_stab
        * v_type_multiplier
        * v_hit_count;

    IF v_damage < 0 THEN
        SET v_damage = 0;
    END IF;

    SET v_percent = (v_damage / v_defender_effective_hp) * 100.0;
    RETURN ROUND(v_percent, 4);
END$$

DELIMITER ;

