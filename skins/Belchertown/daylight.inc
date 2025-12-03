## daylight module
## celestial module for weewx skins
## Copyright Tom Keffer, Matthew Wall
## See LICENSE.txt for your rights
#errorCatcher Echo
## If extended almanac information is available, do extra calculations.
#if $almanac.hasExtras
  #import locale
  #set $sunrise_ts = $almanac.sun.rise.raw
  #set $sunset_ts = $almanac.sun.set.raw
  #if $sunrise_ts and $sunset_ts
    #set $daylight_str = $obs.label.daylight
    #set $now = $current.dateTime.raw
    #set $today_daylight = $sunset_ts -  $sunrise_ts
    #set $seconds = $today_daylight
    #set $hours = $seconds // 3600
    #set $seconds %= 3600
    #set $minutes = $seconds // 60
    #set $seconds %= 60
    #set $yesterday = $now - 24*3600
    #set $yesterday_daylight = $almanac($almanac_time=$yesterday).sun.set.raw - $almanac($almanac_time=$yesterday).sun.rise.raw
    #set $difference = $today_daylight - $yesterday_daylight
    #if $difference
      #set $delta = abs($difference)
      #set $minute_difference = (int($delta) // 60)
      #set $minutes_text = $obs.label.minute[0] if ( $minute_difference == 1 ) else $obs.label.minute[1]
      #set $seconds_text = $obs.label.second[0] if ( int($delta) == 1 ) else $obs.label.second[1]
      #set $amt_str = "%s%d %s" % (str(int($delta) // 60) + ' ' + $minutes_text + ' ' if ($delta // 60) > 0 else '', $delta % 60 if ($delta // 60) > 0 else $delta, $seconds_text)
      #if $difference > 0
        #set $delta_str = "%s %s" % ( $amt_str, $obs.label.daylight_increase )
      #else
        #set $delta_str = "%s %s" % ( $amt_str, $obs.label.daylight_decrease )
      #end if
      #set $daylight_str = "%s %s %s" % ( $daylight_str, ": ", $delta_str )
    #end if
  #end if
#end if
$daylight_str
