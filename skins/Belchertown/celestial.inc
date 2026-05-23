## celestial module for WeeWX skins
## Copyright Tom Keffer, Matthew Wall
## See LICENSE.txt for your rights
#errorCatcher Echo
## If extended almanac information is available, do extra calculations.
#if $almanac.hasExtras
  #import locale
  #set $sun_azimuth = locale.format_string( "%.1f&deg;", $almanac.sun.az )
  #set $sun_ra = locale.format_string( "%.1f&deg;", $almanac.sun.ra )
  #set $sun_dec = locale.format_string( "%.1f&deg;", $almanac.sun.dec )
  #set $moon_azimuth = locale.format_string( "%.1f&deg;", $almanac.moon.az )
  #set $moon_altitude = locale.format_string( "%.1f&deg;", $almanac.moon.alt )
  #set $moon_ra = locale.format_string( "%.1f&deg;", $almanac.moon.ra )
  #set $moon_dec = locale.format_string( "%.1f&deg;", $almanac.moon.dec )
  #set $sun_altitude = $almanac.sun.alt
  #include "almanac_daylight_data.inc"
  #set $sun_altitude = locale.format_string( "%.1f&deg;", $almanac.sun.alt )
#end if
## Compressed for the weewx_data.json file to stay consistent
<div id='celestial_widget' class='widget'> <div class='widget_contents'> <div id='celestial_details'> <div class='celestial_body'> <table class='celestial'> <tr><th>&#9728; $obs.label.sun</th><th></th></tr> <tr> <td class='label'>$obs.label.start_civil_twilight</td> <td class='data'>$almanac(horizon=-6).sun(use_center=1).rise</td> </tr> <tr> <td class='label'>$obs.label.rise</td> <td class='data'>$almanac.sun.rise.format(None_string=$sun_None)</td> </tr> <tr> <td class='label'>$obs.label.transit</td> <td class='data'>$almanac.sun.transit</td> </tr> <tr> <td class='label'>$obs.label.set</td> <td class='data'>$almanac.sun.set.format(None_string=$sun_None)</td> </tr> <tr> <td class='label'>$obs.label.end_civil_twilight</td> <td class='data'>$almanac(horizon=-6).sun(use_center=1).set</td> </tr> <tr> <td class='label'>$obs.label.azimuth</td> <td class='data'>$sun_azimuth</td> </tr> <tr> <td class='label'>$obs.label.altitude</td> <td class='data'>$sun_altitude</td> </tr> <tr> <td class='label'>$obs.label.right_ascension</td> <td class='data'>$sun_ra</td> </tr> <tr> <td class='label'>$obs.label.declination</td> <td class='data'>$sun_dec</td> </tr>#slurp
#if $almanac.next_equinox.raw < $almanac.next_solstice.raw
## The equinox is before the solstice. Display them in order.
<tr><td class='label'>$obs.label.equinox</td><td class='data'>$almanac.next_equinox</td></tr><tr><td class='label'>$obs.label.solstice</td><td class='data'>$almanac.next_solstice</td></tr>#slurp
#else
## The solstice is before the equinox. Display them in order.
<tr><td class='label'>$obs.label.solstice</td><td class='data'>$almanac.next_solstice</td></tr><tr><td class='label'>$obs.label.equinox</td><td class='data'>$almanac.next_equinox</td></tr>#slurp
#end if
<tr> <td class='label'>$obs.label.total_daylight</td> <td class='data'>$daylight_str</td> </tr> </table> </div> <div class='celestial_body'> <table class='celestial'> <tr><th>&#9789; $obs.label.moon</th><th></th></tr> <tr><td class='label'>&nbsp;</td><td class='data'>&nbsp;</td></tr> <tr> <td class='label'>$obs.label.rise</td> <td class='data'>$almanac.moon.rise</td> </tr> <tr> <td class='label'>$obs.label.transit</td> <td class='data'>$almanac.moon.transit</td> </tr> <tr> <td class='label'>$obs.label.set</td> <td class='data'>$almanac.moon.set</td> </tr> <tr><td class='label'>&nbsp;</td><td class='data'>&nbsp;</td></tr> <tr> <td class='label'>$obs.label.azimuth</td> <td class='data'>$moon_azimuth</td> </tr> <tr> <td class='label'>$obs.label.altitude</td> <td class='data'>$moon_altitude</td> </tr> <tr> <td class='label'>$obs.label.right_ascension</td> <td class='data'>$moon_ra</td> </tr> <tr> <td class='label'>$obs.label.declination</td> <td class='data'>$moon_dec</td> </tr>#slurp
#if $almanac.next_full_moon.raw < $almanac.next_new_moon.raw
<tr> <td class='label'>$obs.label.full_moon</td> <td class='data'>$almanac.next_full_moon</td> </tr> <tr> <td class='label'>$obs.label.new_moon</td> <td class='data'>$almanac.next_new_moon</td> </tr>#slurp
#else
<tr> <td class='label'>$obs.label.new_moon</td> <td class='data'>$almanac.next_new_moon</td> </tr> <tr> <td class='label'>$obs.label.full_moon</td> <td class='data'>$almanac.next_full_moon</td> </tr>#slurp
#end if
<tr> <td class='label'>$obs.label.phase</td> <td class='data'>$almanac.moon_phase<br/> $almanac.moon_fullness% $obs.label.full</td> </tr> </table> </div> </div> </div> </div> <div class='clear'></div><div class='almanac_last_updated'></div>
