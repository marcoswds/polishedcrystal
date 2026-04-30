CREATE DATABASE IF NOT EXISTS pokemon_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE pokemon_db;

CREATE TABLE IF NOT EXISTS types (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(32) NOT NULL,
  name VARCHAR(64) NOT NULL,
  UNIQUE KEY uq_types_code (code),
  UNIQUE KEY uq_types_name (name)
);

CREATE TABLE IF NOT EXISTS pokemon (
  id INT AUTO_INCREMENT PRIMARY KEY,
  species_code VARCHAR(64) NOT NULL,
  form_code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  hp INT NOT NULL,
  atk INT NOT NULL,
  def INT NOT NULL,
  sat INT NOT NULL,
  sdf INT NOT NULL,
  spe INT NOT NULL,
  height_dm INT NOT NULL,
  weight_tenths_kg INT NOT NULL,
  bst INT NOT NULL,
  evolution_form ENUM('lvl_up', 'stones', 'others') NULL,
  evolution_level INT NULL,
  evolution_requirement VARCHAR(255) NULL,
  primary_type_id INT NOT NULL,
  secondary_type_id INT NULL,
  UNIQUE KEY uq_pokemon_species_form (species_code, form_code),
  KEY idx_pokemon_name (name),
  KEY idx_pokemon_type1 (primary_type_id),
  KEY idx_pokemon_type2 (secondary_type_id),
  CONSTRAINT fk_pokemon_primary_type
    FOREIGN KEY (primary_type_id) REFERENCES types(id),
  CONSTRAINT fk_pokemon_secondary_type
    FOREIGN KEY (secondary_type_id) REFERENCES types(id)
);

CREATE TABLE IF NOT EXISTS abilities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  description TEXT NOT NULL,
  UNIQUE KEY uq_abilities_code (code),
  UNIQUE KEY uq_abilities_name (name)
);

CREATE TABLE IF NOT EXISTS pokemon_abilities (
  pokemon_id INT NOT NULL,
  ability_id INT NOT NULL,
  slot TINYINT NOT NULL,
  PRIMARY KEY (pokemon_id, ability_id, slot),
  KEY idx_pokemon_abilities_pokemon (pokemon_id),
  KEY idx_pokemon_abilities_ability (ability_id),
  CONSTRAINT fk_pokemon_abilities_pokemon
    FOREIGN KEY (pokemon_id) REFERENCES pokemon(id),
  CONSTRAINT fk_pokemon_abilities_ability
    FOREIGN KEY (ability_id) REFERENCES abilities(id)
);

CREATE TABLE IF NOT EXISTS moves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  description TEXT NOT NULL,
  effect VARCHAR(64) NOT NULL,
  power INT NULL,
  accuracy INT NULL,
  pp INT NOT NULL,
  effect_chance INT NOT NULL,
  category ENUM('PHYSICAL', 'SPECIAL', 'STATUS') NOT NULL,
  type_id INT NOT NULL,
  UNIQUE KEY uq_moves_code (code),
  UNIQUE KEY uq_moves_name (name),
  KEY idx_moves_type (type_id),
  CONSTRAINT fk_moves_type
    FOREIGN KEY (type_id) REFERENCES types(id)
);

CREATE TABLE IF NOT EXISTS type_defensive_relations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  type1_id INT NOT NULL,
  type2_id INT NULL,
  type3_id INT NOT NULL,
  type2_id_key INT AS (IFNULL(type2_id, 0)) STORED,
  relation ENUM('Immune', '2x resist', 'Resist', 'Normal', 'Super effective', '2x super effective') NOT NULL,
  UNIQUE KEY uq_type_def_rel_triplet (type1_id, type2_id_key, type3_id),
  KEY idx_type_def_rel_type1 (type1_id),
  KEY idx_type_def_rel_type2 (type2_id),
  KEY idx_type_def_rel_type3 (type3_id),
  CONSTRAINT fk_type_def_rel_type1
    FOREIGN KEY (type1_id) REFERENCES types(id),
  CONSTRAINT fk_type_def_rel_type2
    FOREIGN KEY (type2_id) REFERENCES types(id),
  CONSTRAINT fk_type_def_rel_type3
    FOREIGN KEY (type3_id) REFERENCES types(id)
);

CREATE TABLE IF NOT EXISTS pokemon_moves (
  pokemon_id INT NOT NULL,
  move_id INT NOT NULL,
  learn_method ENUM('level_up', 'prev_evo_lvl_up', 'tm_hm', 'tutor') NOT NULL,
  learn_level INT NOT NULL DEFAULT 0,
  PRIMARY KEY (pokemon_id, move_id, learn_method, learn_level),
  KEY idx_pokemon_moves_pokemon (pokemon_id),
  KEY idx_pokemon_moves_move (move_id),
  CONSTRAINT fk_pokemon_moves_pokemon
    FOREIGN KEY (pokemon_id) REFERENCES pokemon(id),
  CONSTRAINT fk_pokemon_moves_move
    FOREIGN KEY (move_id) REFERENCES moves(id)
);
